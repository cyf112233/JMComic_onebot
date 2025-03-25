#!/bin/bash
cd jm_bot
# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "未找到Python3，请先安装Python3"
    exit 1
fi

# 检查pip是否安装
if ! command -v pip3 &> /dev/null; then
    echo "未找到pip3，请先安装pip3"
    exit 1
fi

# 检查虚拟环境是否存在
if [ ! -d "venv" ]; then
    echo "正在创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "正在安装依赖..."
pip install -r requirements.txt

# 启动机器人
echo "正在启动机器人..."
python3 bot.py 
