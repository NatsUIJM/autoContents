#!/usr/bin/env python3
"""构建 autoContents 自包含便携包。

用 py-app-standalone（底层是 uv + python-build-standalone）生成一个自包含、
可重定位的 Python 运行环境，再把项目源码与启动器放进去，最终打成 zip。

产物不签名的前提是「不触发系统安全机制」：
- macOS 不进 .app bundle，避开 Gatekeeper
- Windows 不发 .exe，避开 SmartScreen

用法：
    uv run tools/build_bundle.py --target macos-arm64
    uv run tools/build_bundle.py --target windows-x64
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE_NAME = "autoContents"

# Windows 控制台默认 cp1252/cp936，无法编码本脚本里的中文输出，
# 会在第一处 print 就抛 UnicodeEncodeError。统一切到 UTF-8 并对无法
# 编码的字符降级处理，保证构建流程不会因日志中断。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# 项目运行所需的文件/目录（相对项目根）
INCLUDE_ITEMS = [
    "app.py",
    "mcp_server.py",
    "mainprogress",
    "contents_editor",
    "templates",
    "static",
]
# 排除的运行时垃圾
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".log", ".db", ".db-wal", ".db-shm"}
EXCLUDE_NAMES = {"__pycache__", ".DS_Store", ".git", ".temp", ".lock"}

# 启动器模板：{python} 会被替换为 bundle 内解释器的相对路径
LAUNCHER_SH = """#!/bin/zsh
# autoContents 启动器（便携版）
cd "$(dirname "$0")" || exit 1

PY="{python}"
if [ ! -x "$PY" ]; then
  echo "错误：找不到内置 Python 解释器 $PY"
  echo "请确认解压时保留了目录结构与可执行权限。"
  read -r "REPLY?按回车键退出..."
  exit 1
fi

# 优先用默认端口，被占用时自动换端口
exec "$PY" app.py
"""

LAUNCHER_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY={python}"
if not exist "%PY%" (
  echo 错误：找不到内置 Python 解释器 %PY%
  pause
  exit /b 1
)
"%PY%" app.py
pause
"""


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """执行命令，失败时把子进程输出直接打出来。

    check=True 的默认 traceback 只显示命令本身，看不到子进程报了什么；
    构建失败时必须能看到真实 stderr，否则只能靠猜。
    """
    result = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if result.returncode != 0:
        sys.stderr.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        raise SystemExit(f"命令失败（exit {result.returncode}）: {' '.join(cmd[:3])} ...")
    return result


def read_direct_deps(pyproject: Path) -> list[str]:
    """读出 pyproject.toml 里的直接依赖（不含二级依赖）。

    只装主依赖，二级依赖交给 uv 自己解析——这正是 uv 的正常行为，也避免了
    把 uv.lock 里其它平台的包（如仅限Windows 的 pywin32）硬塞进来导致安装失败。
    版本用 >= 下限而非锁定：便携包的用户拿到的是「当前能装的版本」，锁死版本
    反而会让新用户在几个月后因为上游发新版而装不上。
    """
    import tomllib

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    if not deps:
        raise SystemExit(f"{pyproject.name} 中未找到 project.dependencies")
    return [d.strip() for d in deps if d.strip() and not d.strip().startswith("#")]


def find_python_root(py_standalone: Path) -> Path:
    """定位 py-standalone 内的 CPython 安装目录（含 bin/ 与 lib/）。

    注意 py-app-standalone 会同时留下两个目录：真实目录
    cpython-X.Y.Z-<platform> 与一个指向它的符号链接cpython-X.Y-<platform>。
    真实目录名带补丁号，才是要用的那个。
    """
    candidates = [
        c
        for c in sorted(py_standalone.iterdir())
        if c.is_dir() and not c.is_symlink() and (c / "bin").is_dir()
    ]
    if not candidates:
        raise SystemExit(f"未在 {py_standalone} 中找到 CPython 安装目录")
    return candidates[0]


def fix_symlink(bundle: Path) -> None:
    """把 py-app-standalone 生成的绝对路径符号链接改成相对链接。

    该工具会建`cpython-X.Y-macos-aarch64-none -> /绝对路径/...` 的别名，
    目录一旦移动或被 zip 打包解包到别处就会断裂。必须修正为相对链接。
    """
    real = find_python_root(bundle)
    for item in bundle.iterdir():
        if item.is_symlink() and not item.is_dir():
            continue
        if item == real:
            continue
        if item.is_symlink():
            target = os.readlink(item)
            if os.path.isabs(target):
                item.unlink()
                item.symlink_to(real.name)
                print(f"  修正符号链接为相对路径: {item.name} -> {real.name}")


def codesign_all(bundle: Path) -> None:
    """对 bundle 内所有 Mach-O 做 ad-hoc 签名。

    arm64 macOS 要求所有可执行代码必须有签名，否则内核直接 SIGKILL 且
    没有任何错误提示。自底向上签名（叶子 → 根），签名必须是最后一步。
    """
    binaries: list[Path] = []
    for path in bundle.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix in (".so", ".dylib") or path.name == "python3.13":
            binaries.append(path)

    # 自底向上：路径越长越深（叶子在前）
    binaries.sort(key=lambda p: len(p.parts), reverse=True)

    for path in binaries:
        subprocess.run(
            ["codesign", "--force", "--sign", "-", str(path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # 逐个验证，签名无效会让用户看到 "app is damaged"
    failed = []
    for path in binaries:
        result = subprocess.run(
            ["codesign", "--verify", "--strict", str(path)],
            capture_output=True,
        )
        if result.returncode != 0:
            failed.append(path)
    if failed:
        raise SystemExit("签名校验失败:\n" + "\n".join(str(p) for p in failed))
    print(f"  已签名并校验 {len(binaries)} 个 Mach-O")


def copy_project(dest: Path) -> None:
    """拷贝项目源码到 bundle，清掉运行时垃圾。"""
    for item in INCLUDE_ITEMS:
        src = ROOT / item
        if not src.exists():
            continue
        target = dest / item
        if src.is_dir():
            shutil.copytree(
                src,
                target,
                ignore=shutil.ignore_patterns(*EXCLUDE_NAMES, "*.pyc", "*.log"),
            )
        else:
            shutil.copy2(src, target)


def write_launcher(bundle: Path, target: str) -> None:
    py_root = find_python_root(bundle / "py-standalone")
    if target.startswith("macos"):
        rel = f"py-standalone/{py_root.name}/bin/python3.13"
        launcher = bundle / "启动 autoContents.command"
        launcher.write_text(LAUNCHER_SH.replace("{python}", rel), encoding="utf-8")
        # 双击 .command 必须有执行权限
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    else:
        rel = f"py-standalone\\{py_root.name}\\python.exe"
        launcher = bundle / "启动 autoContents.bat"
        launcher.write_text(
            LAUNCHER_BAT.replace("{python}", rel), encoding="utf-8"
        )


def make_zip(bundle: Path, out: Path) -> Path:
    """打包成 zip。

    macOS 必须用 ditto：通用 zip 库会丢失 Unix 可执行权限位，导致
    .command 解压后双击无反应。
    """
    if sys.platform == "darwin":
        subprocess.run(
            [
                "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                str(bundle), str(out),
            ],
            check=True,
        )
    else:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(bundle.rglob("*")):
                zf.write(path, path.relative_to(bundle.parent))
    return out


def smoke_test(bundle: Path, target: str) -> None:
    """冒烟测试：确认关键依赖能导入、app 能启动。

    便携包最常见的失败是「打包成功但用户一跑就崩」，必须在这里拦住。
    """
    py_root = find_python_root(bundle / "py-standalone")
    exe = (
        py_root / "bin" / "python3.13"
        if target.startswith("macos")
        else py_root / "python.exe"
    )
    code = (
        "import pymupdf, pikepdf, PIL, flask, fastmcp, openai, dotenv;"
        "import sys;"
        "sys.path.insert(0, '.');"
        "import app;"
        "print('smoke-ok')"
    )
    result = subprocess.run(
        [str(exe), "-c", code], cwd=bundle, capture_output=True, text=True
    )
    if "smoke-ok" not in result.stdout:
        raise SystemExit(
            f"冒烟测试失败:\nstdout: {result.stdout[-800:]}\n"
            f"stderr: {result.stderr[-800:]}"
        )
    print("  冒烟测试通过（依赖导入 + app 加载）")


def cleanup_temp_dirs(bundle: Path) -> None:
    """删除 py-app-standalone 留下的临时目录与锁文件。"""
    for name in (".temp", ".lock", ".gitignore"):
        target = bundle / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 autoContents 便携包")
    parser.add_argument(
        "--target",
        required=True,
        choices=["macos-arm64", "macos-x64", "windows-x64"],
        help="目标平台（需在对应平台/架构上构建）",
    )
    parser.add_argument("--out", default="dist", help="输出目录")
    parser.add_argument(
        "--python-version", default="3.13", help="内置 Python 版本"
    )
    args = parser.parse_args()

    is_macos = args.target.startswith("macos")
    out_dir = ROOT / args.out
    out_dir.mkdir(exist_ok=True)

    # py-app-standalone 会在构建目录里做绝对路径替换（含 .pyc 二进制），
    # 路径太长会导致替换匹配失败（实测在项目内构建时报
    # "Found N matches ... in binary files"）。因此在短临时目录里构建，
    # 完成后再把产物搬到输出目录。
    with tempfile.TemporaryDirectory(prefix="acbuild-") as tmp:
        tmp_bundle = Path(tmp) / "b"
        tmp_bundle.mkdir()
        bundle = tmp_bundle / BUNDLE_NAME
        bundle.mkdir()
        build_into(bundle, args, is_macos)
        zip_path = out_dir / f"{BUNDLE_NAME}-{args.target}.zip"
        make_zip(bundle, zip_path)

    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"\n完成: {zip_path.relative_to(ROOT)} ({size_mb:.1f} MB)")
    return 0


def build_into(bundle: Path, args: argparse.Namespace, is_macos: bool) -> None:
    """在给定目录里完成 1~5 步（不含打包）。"""
    # 1. 生成自包含 Python 环境
    # 只传主依赖：二级依赖由 uv 自动解析，且会自动跳过当前平台装不上的包。
    print(f"[1/6] 构建自包含 Python {args.python_version} ({args.target})")
    packages = read_direct_deps(ROOT / "pyproject.toml")
    print(f"  直接依赖 {len(packages)} 个（其余由 uv 解析）")
    run(
        [
            "uvx", "py-app-standalone",
            "--target", str(bundle / "py-standalone"),
            "--python-version", args.python_version,
            "--force",
            *packages,
        ],
        cwd=ROOT,
    )
    cleanup_temp_dirs(bundle / "py-standalone")

    # 2. 修掉绝对路径符号链接
    print("[2/6] 修正符号链接为可重定位")
    fix_symlink(bundle / "py-standalone")

    # 3.拷入项目源码
    print("[3/6] 拷入项目源码")
    copy_project(bundle)

    # 4. 写启动器
    print("[4/6] 生成启动器")
    write_launcher(bundle, args.target)

    # 5. 签名（仅 macOS，必须在所有文件写入之后）
    if is_macos:
        print("[5/6] ad-hoc 签名所有 Mach-O")
        codesign_all(bundle)
    else:
        print("[5/6] Windows 无需签名（不产生 .exe，避开 SmartScreen）")

    # 6. 冒烟测试
    print("[6/6] 冒烟测试")
    smoke_test(bundle, args.target)


if __name__ == "__main__":
    sys.exit(main())
