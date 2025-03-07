#!/bin/zsh

# 获取脚本所在目录
SCRIPT_DIR=$(dirname "$0")

# 输出脚本所在目录
echo "脚本所在目录: $SCRIPT_DIR"

# 切换到脚本所在目录
cd "$SCRIPT_DIR"

# 输出当前工作目录以确认切换成功
echo "当前工作目录: $(pwd)"

# 激活虚拟环境
cd ..
source .venv/bin/activate

# 运行程序
cd tools
python qwen_test.py