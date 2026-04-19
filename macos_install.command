#!/bin/zsh

# 0. 获取脚本所在目录并进入
cd "${0:a:h}" || exit 1

# 1. 安装/触发 Xcode Command Line Tools (若已安装则忽略错误)
xcode-select --install 2>/dev/null || true

# 2. 删除旧的虚拟环境并创建新的
rm -rf .venv
python3 -m venv .venv

# 3. 激活虚拟环境
source .venv/bin/activate

# 4. 设置 pip 镜像源
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple

# 5. 安装依赖 (设置超时时间为 300 秒)
pip install --timeout 300 -r requirements.txt

# 6. 给予运行权限
chmod +x macos_start.command