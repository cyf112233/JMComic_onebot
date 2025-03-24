#!/bin/bash
cd jm_bot
# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到Python3，请先安装Python3"
    read -p "按回车键退出..."
    exit 1
fi

# 检查Python版本
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
if (( $(echo "$python_version < 3.8" | bc -l) )); then
    echo "错误: Python版本必须 >= 3.8，当前版本: $python_version"
    read -p "按回车键退出..."
    exit 1
fi

echo "Python环境检查通过 (版本: $python_version)"

# 启动机器人
echo "正在启动机器人..."
python3 bot.py

# 如果发生错误，等待用户按回车键后退出
read -p "按回车键退出..." 