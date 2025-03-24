@echo off
cd jm_bot
chcp 65001 > nul
echo 正在检查Python环境...

python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python
    pause
    exit /b 1
)

for /f "tokens=2 delims=." %%a in ('python -c "import sys; print(sys.version.split()[0])"') do set python_version=%%a
if %python_version% LSS 8 (
    echo 错误: Python版本必须 ^>= 3.8
    pause
    exit /b 1
)

echo Python环境检查通过
echo 正在启动机器人...
python bot.py 