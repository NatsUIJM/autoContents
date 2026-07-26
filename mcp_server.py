"""autoContents MCP 服务器。

为扫描版 PDF 自动生成可跳转书签（基于目录页识别）。

LLM 配置通过环境变量传入（在 MCP 客户端配置中设置 env）：
- AUTOCONTENTS_API_KEY   必填，OpenAI 兼容接口的 API Key
- AUTOCONTENTS_BASE_URL  可选，默认 https://dashscope.aliyuncs.com/compatible-mode/v1
- AUTOCONTENTS_MODEL     可选，默认 qwen3.5-397b-a17b

Cherry Studio / Claude Desktop 配置示例：
{
  "mcpServers": {
    "autoContents": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/autoContents", "python", "/path/to/autoContents/mcp_server.py"],
      "env": {
        "AUTOCONTENTS_API_KEY": "sk-xxx",
        "AUTOCONTENTS_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "AUTOCONTENTS_MODEL": "qwen3.7-plus"
      }
    }
  }
}
"""

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP

from mainprogress.llm_config import load_llm_config
from mainprogress.pipeline import process_pdfs, sanitize_filename

WORK_ROOT = PROJECT_ROOT / "data"

mcp = FastMCP("autoContents")


def _deliver_output(result, output_dir: Path | None) -> str:
    """将产物 PDF 复制到交付目录（或源文件同目录），返回最终路径。"""
    if not result.output_pdf:
        return ""
    src = Path(result.output_pdf)
    if result.book_name and sanitize_filename(result.book_name):
        filename = f"{sanitize_filename(result.book_name)}.pdf"
    else:
        filename = src.name
    dest_dir = output_dir if output_dir else Path(result.source_path).parent
    dest = dest_dir / filename
    # 避免覆盖已存在文件
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{dest.stem}_{counter}{dest.suffix}"
        counter += 1
    shutil.copy2(src, dest)
    return str(dest)


@mcp.tool
def generate_pdf_bookmarks(pdf_paths: list[str], output_dir: str = "") -> str:
    """为一个或多个扫描版 PDF 自动生成书签（目录）。

    每个 PDF 依次执行完整流水线：元数据提取 → 目录页转图 → VL 提取目录 →
    层级判定 → 后处理 → 写回 PDF 书签。单个文件失败不影响其余文件。

    Args:
        pdf_paths: PDF 文件的绝对路径列表。
        output_dir: 可选，产物输出目录（绝对路径）。缺省时输出到各源文件所在目录。

    Returns:
        JSON 字符串，包含每个文件的处理状态、产物路径与错误信息。
    """
    # 1. 校验 LLM 配置
    try:
        cfg = load_llm_config()
    except ValueError as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    # 2. 校验输入路径
    valid_paths = []
    path_errors = []
    for p in pdf_paths:
        path = Path(p)
        if not path.is_absolute():
            path_errors.append({"path": p, "error": "不是绝对路径"})
        elif not path.exists():
            path_errors.append({"path": p, "error": "文件不存在"})
        elif path.suffix.lower() != ".pdf":
            path_errors.append({"path": p, "error": "不是 PDF 文件"})
        else:
            valid_paths.append(path)

    out_dir = None
    if output_dir:
        out_dir = Path(output_dir)
        if not out_dir.is_absolute():
            return json.dumps(
                {"status": "error", "message": f"output_dir 必须是绝对路径：{output_dir}"},
                ensure_ascii=False,
            )
        out_dir.mkdir(parents=True, exist_ok=True)

    if not valid_paths:
        return json.dumps({
            "status": "error",
            "message": "没有有效的 PDF 文件",
            "path_errors": path_errors,
        }, ensure_ascii=False)

    # 3. 串行执行流水线
    results = process_pdfs(valid_paths, work_root=WORK_ROOT)

    files = []
    for r in path_errors:
        files.append({"source": r["path"], "ok": False, "error": r["error"]})
    for r in results:
        entry = {
            "source": r.source_path,
            "ok": r.ok,
            "book_name": r.book_name,
            "session_dir": r.base_dir,
        }
        if r.ok:
            entry["output_pdf"] = _deliver_output(r, out_dir)
        else:
            entry["failed_step"] = r.failed_step
            entry["error"] = r.error
        files.append(entry)

    succeeded = sum(1 for f in files if f["ok"])
    return json.dumps({
        "status": "success" if succeeded == len(files) else "partial",
        "model": cfg["model"],
        "total": len(files),
        "succeeded": succeeded,
        "failed": len(files) - succeeded,
        "files": files,
    }, ensure_ascii=False, indent=2)


@mcp.tool
def check_llm_config() -> str:
    """检查当前 LLM 配置是否可用（来源、base_url、model，不泄露完整 key）。"""
    try:
        cfg = load_llm_config()
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    key = cfg["api_key"]
    masked = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else "***"
    return json.dumps({
        "ok": True,
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "api_key": masked,
    }, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
