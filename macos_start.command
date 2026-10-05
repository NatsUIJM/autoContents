#!/bin/zsh

# 获取脚本所在目录
SCRIPT_DIR=$(dirname "$0")

# 切换到脚本所在目录
cd "$SCRIPT_DIR"

# 直接使用虚拟环境中的 python 解释器绝对路径
# 假设虚拟环境目录名为 .venv
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# 检查解释器是否存在
if [ ! -f "$VENV_PYTHON" ]; then
    echo "错误: 找不到虚拟环境解释器 $VENV_PYTHON"
    exit 1
fi

# 运行程序
"$VENV_PYTHON" app.py