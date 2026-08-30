"""PDF 书签生成流水线编排模块。

集中管理原先散落在 app.py 中的：
- 会话目录创建与 PDF 入库（拼音重命名 + 初始 JSON）
- 各步骤子进程的环境变量构造
- 6 个步骤的串行执行与结果收集

app.py（Web 逐步调进度）与 mcp_server.py（批量处理）共用本模块。
"""

import json
import os
import random
import re
import shutil
import string
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pypinyin import lazy_pinyin

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

STEP_SEQUENCE = [
    ("pdf_metadata_extractor", "PDF 元数据提取"),
    ("pdf_to_image", "PDF 转 JPG"),
    ("qwen_vl_extract", "目录数据提取"),
    ("determine_toc_levels", "目录层级确定"),
    ("content_postprocessor", "目录后处理"),
    ("pdf_generator", "生成 PDF"),
]

DATA_FOLDERS = [
    "input_pdf",
    "mark/input_image",
    "raw_content",
    "output_pdf",
    "mark/image_metadata",
    "merged_content",
]

DEFAULT_STEP_TIMEOUT = 3000


@dataclass
class StepResult:
    index: int
    name: str
    desc: str
    ok: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str = ""


@dataclass
class PdfResult:
    source_path: str
    ok: bool = False
    session_id: str = ""
    base_dir: str = ""
    output_pdf: str = ""
    book_name: str = ""
    failed_step: str = ""
    error: str = ""
    steps: list = field(default_factory=list)


def generate_session_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(6))
    return f"{timestamp}_{suffix}"


def pinyin_name(original_filename: str) -> str:
    """中文文件名转拼音（截断 25 字符），保留扩展名。"""
    stem, ext = os.path.splitext(original_filename)
    pinyin = "".join(lazy_pinyin(stem))
    if len(pinyin) > 25:
        pinyin = pinyin[:25]
    return pinyin + ext


def create_session(work_root: str | Path = "data") -> tuple[str, Path]:
    """创建会话目录结构，返回 (session_id, base_dir)。"""
    session_id = generate_session_id()
    base_dir = Path(work_root) / session_id
    for folder in DATA_FOLDERS:
        (base_dir / folder).mkdir(parents=True, exist_ok=True)
    return session_id, base_dir


def write_initial_json(base_dir: str | Path, pinyin_filename: str, original_filename: str) -> Path:
    """写入初始元数据 JSON，返回 JSON 路径。"""
    json_path = Path(base_dir) / "input_pdf" / (os.path.splitext(pinyin_filename)[0] + ".json")
    initial_data = {
        "toc_start": 0,
        "toc_end": 0,
        "content_start": 0,
        "original_filename": original_filename,
        "book_name": "",
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(initial_data, f, ensure_ascii=False, indent=4)
    return json_path


def stage_pdf(base_dir: str | Path, src_path: str | Path, original_filename: str | None = None) -> Path:
    """将 PDF 复制进会话 input_pdf 目录并完成拼音重命名与初始 JSON，返回入库后路径。"""
    src_path = Path(src_path)
    original_filename = original_filename or src_path.name
    dest = Path(base_dir) / "input_pdf" / pinyin_name(original_filename)
    shutil.copy2(src_path, dest)
    write_initial_json(base_dir, dest.name, original_filename)
    return dest


def build_step_env(base_dir: str | Path) -> dict:
    """构造步骤子进程环境变量（含全部历史变量名，保持向后兼容）。"""
    base_dir = str(Path(base_dir).resolve())
    env = os.environ.copy()
    # 透传 LLM 配置环境变量（api_key/base_url/model），避免子进程因环境隔离无法读取。
    # 注意：子进程 load_llm_config() 环境变量优先于配置文件——只要注入了 key，
    # 子进程就走 env 分支；若不同步注入 base_url/model，会回落到默认 dashscope
    # 端点与默认模型，自定义服务商的 key 被发往 dashscope 导致 401。
    try:
        from mainprogress.llm_config import load_llm_config as _load_llm_config
        _cfg = _load_llm_config()
        if _cfg.get("api_key") and not env.get("AUTOCONTENTS_API_KEY"):
            env["AUTOCONTENTS_API_KEY"] = _cfg["api_key"]
        if _cfg.get("base_url") and not env.get("AUTOCONTENTS_BASE_URL"):
            env["AUTOCONTENTS_BASE_URL"] = _cfg["base_url"]
        if _cfg.get("model") and not env.get("AUTOCONTENTS_MODEL"):
            env["AUTOCONTENTS_MODEL"] = _cfg["model"]
    except Exception:
        pass  # 加载失败时静默跳过，子进程会自行处理
    env.update({
        "BASE_DIR": base_dir,
        "PDF_METADATA_EXTRACTOR_INPUT": f"{base_dir}/input_pdf",
        "PDF_METADATA_EXTRACTOR_OUTPUT": f"{base_dir}/input_pdf",
        "PDF2JPG_INPUT": f"{base_dir}/input_pdf",
        "PDF2JPG_OUTPUT": f"{base_dir}/mark/input_image",
        "QWEN_VL_EXTRACT_INPUT": f"{base_dir}/mark/input_image",
        "QWEN_VL_EXTRACT_OUTPUT": f"{base_dir}/raw_content",
        # 历史遗留变量名，旧版 app.py 使用，部分脚本未读取但保留无害
        "QWEN_VL_INPUT": f"{base_dir}/mark/input_image",
        "QWEN_VL_OUTPUT": f"{base_dir}/automark_raw_data",
        "CONTENT_POSTPROCESSOR_INPUT": f"{base_dir}/raw_content",
        "CONTENT_POSTPROCESSOR_OUTPUT": f"{base_dir}/level_adjusted_content",
        "PDF_GENERATOR_INPUT_1": f"{base_dir}/level_adjusted_content",
        "PDF_GENERATOR_INPUT_2": f"{base_dir}/input_pdf",
        "PDF_GENERATOR_OUTPUT_1": f"{base_dir}/output_pdf",
    })
    return env


def run_step(index: int, base_dir: str | Path, timeout: int = DEFAULT_STEP_TIMEOUT) -> StepResult:
    """执行流水线中的单个步骤（子进程方式，保持脚本间隔离）。"""
    name, desc = STEP_SEQUENCE[index]
    script_path = SCRIPT_DIR / f"{name}.py"
    env = build_step_env(base_dir)

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            env=env,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return StepResult(
            index=index, name=name, desc=desc,
            ok=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
    except subprocess.TimeoutExpired as e:
        return StepResult(
            index=index, name=name, desc=desc,
            ok=False, timed_out=True,
            stdout=(e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout) or "",
            stderr=(e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr) or "",
            error=f"步骤执行超时（{timeout} 秒）",
        )
    except Exception as e:
        return StepResult(index=index, name=name, desc=desc, ok=False, error=str(e))


def read_book_name(base_dir: str | Path) -> str:
    """从会话 input_pdf 的 JSON 中读取书名。"""
    input_dir = Path(base_dir) / "input_pdf"
    for json_file in input_dir.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                name = json.load(f).get("book_name", "")
            if name:
                return name
        except Exception:
            continue
    return ""


def find_output_pdf(base_dir: str | Path) -> str:
    """定位会话输出目录中的 PDF。"""
    output_dir = Path(base_dir) / "output_pdf"
    pdfs = sorted(output_dir.glob("*.pdf"))
    return str(pdfs[0]) if pdfs else ""


def sanitize_filename(name: str) -> str:
    """清理文件名中的跨平台非法字符。"""
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


def process_pdf(
    pdf_path: str | Path,
    work_root: str | Path = "data",
    timeout: int = DEFAULT_STEP_TIMEOUT,
    on_step=None,
) -> PdfResult:
    """对单个 PDF 执行完整流水线。

    on_step: 可选回调 fn(step_result, pdf_result)，每步结束后调用。
    """
    pdf_path = Path(pdf_path).resolve()
    result = PdfResult(source_path=str(pdf_path))

    session_id, base_dir = create_session(work_root)
    result.session_id = session_id
    result.base_dir = str(base_dir)

    try:
        stage_pdf(base_dir, pdf_path)
    except Exception as e:
        result.error = f"PDF 入库失败：{e}"
        return result

    for index in range(len(STEP_SEQUENCE)):
        step = run_step(index, base_dir, timeout=timeout)
        result.steps.append(step)
        if on_step:
            on_step(step, result)
        if not step.ok:
            result.failed_step = step.desc
            result.error = step.error or f"{step.desc}失败（exit {step.returncode}）：{step.stderr.strip()[-500:]}"
            return result

    result.ok = True
    result.output_pdf = find_output_pdf(base_dir)
    result.book_name = read_book_name(base_dir)
    return result


def process_pdfs(
    pdf_paths,
    work_root: str | Path = "data",
    timeout: int = DEFAULT_STEP_TIMEOUT,
    on_step=None,
) -> list:
    """串行处理多个 PDF，单个失败不影响其余，返回 PdfResult 列表。"""
    results = []
    for path in pdf_paths:
        results.append(process_pdf(path, work_root=work_root, timeout=timeout, on_step=on_step))
    return results
