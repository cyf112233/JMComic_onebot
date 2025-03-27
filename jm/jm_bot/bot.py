import os
import sys
import subprocess
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

script_dir = os.path.dirname(os.path.abspath(__file__))

def install_package(package: str):
    print(f"正在安装 {package}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", package])
        print(f"{package} 安装成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"安装 {package} 失败: {e}")
        return False

def check_and_install_dependencies():
    required_packages = {
        'jmcomic': 'jmcomic',
        'aiohttp': 'aiohttp',
        'pyyaml': 'yaml',
        'pillow': 'PIL',
        'pyzipper': 'pyzipper',
        'psutil': 'psutil'
    }
    
    for package, import_name in required_packages.items():
        try:
            __import__(import_name)
            print(f"已安装 {package}")
        except ImportError:
            print(f"缺少依赖: {package}")
            if not install_package(package):
                print(f"无法安装 {package}，请手动安装")
                continue
            try:
                __import__(import_name)
                print(f"已成功导入 {package}")
            except ImportError as e:
                print(f"导入 {package} 失败: {e}")
                continue

check_and_install_dependencies()

import psutil
import re
import random
import string
import zipfile
import pyzipper
import jmcomic
from pathlib import Path
from typing import Optional, Set
import asyncio
from aiohttp import web, ClientSession, ClientError, TCPConnector, ClientTimeout, WSMsgType
import json
import yaml
import time
import shutil
import socket
from jmcomic import JmDownloader, JmOption
import aiohttp
import tempfile
from PIL import Image

def load_config() -> dict:
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "config.yml")
        if not os.path.exists(config_path):
            print(f"配置文件不存在: {config_path}")
            return {}
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            print("配置文件加载成功")
            return config
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return {}

# 先加载配置
CONFIG = load_config()

class ConsoleClearHandler(logging.StreamHandler):
    def __init__(self, max_lines=None):
        super().__init__()
        self.max_lines = max_lines or CONFIG.get('console', {}).get('max_lines', 1000)
        self.line_count = 0
        
    def emit(self, record):
        try:
            msg = self.format(record)
            self.stream.write(msg + self.terminator)
            self.flush()
            
            self.line_count += 1
            if self.line_count >= self.max_lines:
                # 清屏
                os.system('cls' if os.name == 'nt' else 'clear')
                # 重置计数器
                self.line_count = 0
                # 重新显示最后一条日志
                self.stream.write(msg + self.terminator)
                self.flush()
        except Exception:
            self.handleError(record)

# 初始化日志系统
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 根据配置决定是否输出到文件
if CONFIG.get('log', {}).get('file_output', True):
    log_dir = os.path.join(script_dir, "log")
    os.makedirs(log_dir, exist_ok=True)
    current_datetime = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = os.path.join(log_dir, f'bot_{current_datetime}.log')
    
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - 程序启动\n")
    
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    print(f"日志文件输出已启用，日志文件保存在: {log_file}")
else:
    print("日志文件输出已禁用，仅输出到控制台")

# 添加控制台处理器
console_handler = ConsoleClearHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logger.info("日志系统初始化完成")

# 创建配置对象
option = jmcomic.create_option_by_file('jm-option.yml')
logger.info("已加载JM下载配置")

def load_enabled_groups() -> Set[int]:
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        enabled_groups_file = os.path.join(script_dir, "enabled_groups.json")
        if os.path.exists(enabled_groups_file):
            with open(enabled_groups_file, 'r') as f:
                groups = json.load(f)
                return set(groups)
        else:
            logger.warning("已启用群组文件不存在，将创建新文件")
            save_enabled_groups(set())
            return set()
    except Exception as e:
        logger.error(f"加载已启用群组失败: {e}")
        return set()

def save_enabled_groups(groups: Set[int]) -> bool:
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        enabled_groups_file = os.path.join(script_dir, "enabled_groups.json")
        with open(enabled_groups_file, 'w') as f:
            json.dump(list(groups), f)
        logger.info("已保存启用群组列表")
        return True
    except Exception as e:
        logger.error(f"保存已启用群组失败: {e}")
        return False

logger.info("开始加载配置...")
CONFIG = load_config()
logger.info("配置加载完成")

INITIAL_RETRY_INTERVAL = 5
MAX_RETRY_INTERVAL = 300
MAX_RETRY_COUNT = 5

ADMIN_QQ_NUMBERS = set(CONFIG.get('admin', {}).get('qq_numbers', []))
MAX_ZIP_SIZE = CONFIG.get('files', {}).get('max_zip_size', 100) * 1024 * 1024
CLEANUP_INTERVAL = CONFIG.get('cleanup', {}).get('interval', 3600)
ZIP_PASSWORD = CONFIG.get('files', {}).get('password', '123456')
COOLDOWN = CONFIG.get('download', {}).get('cooldown', 60)

PDF_ENABLED = CONFIG.get('pdf', {}).get('enabled', False)
if PDF_ENABLED:
    logger.info("PDF模式已启用，将使用PDF发送方式")
else:
    logger.info("PDF模式未启用，将使用ZIP发送方式")

PDF_API_URL = CONFIG.get('pdf', {}).get('api_url', '')

SERVER_HOST = CONFIG.get('server', {}).get('host', '127.0.0.1')
SERVER_PORT = CONFIG.get('server', {}).get('port', 8080)

ONEBOT_HOST = CONFIG.get('onebot', {}).get('host', '127.0.0.1')
ONEBOT_PORT = CONFIG.get('onebot', {}).get('port', 5700)
ONEBOT_ACCESS_TOKEN = CONFIG.get('onebot', {}).get('access_token', '')

DOWNLOAD_DIR = os.path.join(script_dir, "downloads")
ZIP_DIR = os.path.join(script_dir, "zips")
PDF_DIR = os.path.join(script_dir, "pdf")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(ZIP_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)

ws_client = None
ADMIN_IDS = set()
GROUP_COOLDOWNS = {}

logger.info("开始加载已启用群组...")
ENABLED_GROUPS = load_enabled_groups()
logger.info(f"已加载 {len(ENABLED_GROUPS)} 个已启用群组")

logger.info(f"管理员QQ号: {ADMIN_QQ_NUMBERS}")
logger.info(f"最大文件大小: {MAX_ZIP_SIZE/1024/1024}MB")
logger.info(f"清理间隔: {CLEANUP_INTERVAL}秒")
logger.info(f"ZIP密码: {ZIP_PASSWORD}")
logger.info(f"下载CD时间: {COOLDOWN}秒")
logger.info(f"PDF模式: {'启用' if PDF_ENABLED else '禁用'}")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_QQ_NUMBERS

async def call_onebot_api(endpoint: str, data: dict, retry_count=0) -> Optional[dict]:
    global ws_client
    
    if ws_client is None:
        logger.error("WebSocket未连接，无法发送消息")
        return None
    
    retry_interval = min(INITIAL_RETRY_INTERVAL * (2 ** retry_count), MAX_RETRY_INTERVAL)
    
    try:
        api_data = {
            "action": endpoint,
            "params": data.get("params", {}),
            "echo": str(time.time())
        }
        
        await ws_client.send_json(api_data)
        logger.debug(f"已发送API调用: {api_data}")
        
        async for msg in ws_client:
            if msg.type == WSMsgType.TEXT:
                try:
                    result = json.loads(msg.data)
                    if result.get("echo") == api_data["echo"]:
                        if result.get("status") == "failed":
                            logger.error(f"OneBot API调用失败: {result.get('msg', '未知错误')}")
                            return None
                        return result
                except json.JSONDecodeError as e:
                    logger.error(f"解析API响应失败: {e}")
                    return None
            elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                logger.error(f"WebSocket连接错误: {msg.data}")
                return None
                
    except Exception as e:
        logger.error(f"调用OneBot API失败: {e}")
        logger.info(f"将在 {retry_interval} 秒后重试...")
        await asyncio.sleep(retry_interval)
        return await call_onebot_api(endpoint, data, retry_count + 1)

async def send_group_message(group_id: int, message: str) -> bool:
    data = {
        "action": "send_group_msg",
        "params": {
            "group_id": group_id,
            "message": message
        }
    }
    result = await call_onebot_api("send_msg", data)
    return result is not None

async def handle_admin_command(command: str, group_id: int, user_id: int):
    if not is_admin(user_id):
        await send_group_message(group_id, "抱歉，您没有权限执行此命令。")
        return
    
    if command == "/启用jm":
        if group_id in ENABLED_GROUPS:
            await send_group_message(group_id, "本群已启用JM下载功能。")
            return
        
        ENABLED_GROUPS.add(group_id)
        save_enabled_groups(ENABLED_GROUPS)
        await send_group_message(group_id, "已在本群启用JM下载功能。")
    elif command == "/禁用jm":
        if group_id not in ENABLED_GROUPS:
            await send_group_message(group_id, "本群未启用JM下载功能。")
            return
        
        ENABLED_GROUPS.remove(group_id)
        save_enabled_groups(ENABLED_GROUPS)
        await send_group_message(group_id, "已在本群禁用JM下载功能。")

async def handle_help_command(group_id: int, user_id: int):
    help_text = """可用命令：
/jm <JM号> - 下载指定JM号的漫画
/帮助 - 显示此帮助信息"""

    admin_help = """
管理员命令：
/启用jm - 在本群启用JM下载功能
/禁用jm - 在本群禁用JM下载功能"""

    if is_admin(user_id):
        help_text += admin_help

    await send_group_message(group_id, help_text)

def all2PDF(input_folder, pdfpath, pdfname):
    start_time = time.time()
    paht = input_folder
    zimulu = []
    image = []
    sources = []

    for root, _, files in os.walk(paht):
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.heic', '.heif')):
                image.append(os.path.join(root, file))

    image.sort()

    if not image:
        logger.error("未找到任何图片文件")
        return

    output = Image.open(image[0])
    if output.mode != "RGB":
        output = output.convert("RGB")

    for file in image[1:]:
        try:
            img_file = Image.open(file)
            if img_file.mode != "RGB":
                img_file = img_file.convert("RGB")
            sources.append(img_file)
        except Exception as e:
            logger.error(f"处理图片失败 {file}: {e}")
            continue

    pdf_file_path = os.path.join(pdfpath, pdfname)
    if not pdf_file_path.endswith(".pdf"):
        pdf_file_path = pdf_file_path + ".pdf"

    try:
        output.save(pdf_file_path, "pdf", save_all=True, append_images=sources)
        end_time = time.time()
        run_time = end_time - start_time
        logger.info(f"PDF生成完成，耗时：{run_time:.2f} 秒")
    except Exception as e:
        logger.error(f"保存PDF失败: {e}")
        raise

async def download_pdf(jm_id: str, user_id: str) -> Optional[str]:
    if not PDF_ENABLED:
        return None
        
    try:
        user_download_dir = os.path.join(os.getcwd(), "downloads", str(user_id))
        if not os.path.exists(user_download_dir):
            os.makedirs(user_download_dir)
            
        original_dir = os.getcwd()
        pdf_path = None  # 初始化pdf_path变量
        
        try:
            os.chdir(user_download_dir)
            logger.info(f"切换到用户下载目录: {user_download_dir}")
            
            # 使用绝对路径加载配置文件
            option_path = os.path.join(original_dir, 'jm-option.yml')
            if not os.path.exists(option_path):
                logger.error(f"配置文件不存在: {option_path}")
                return None
                
            # 使用配置文件创建下载选项
            option = jmcomic.create_option_by_file(option_path)
            logger.info("已加载JM下载配置")
            
            # 使用配置选项下载
            jmcomic.download_album(jm_id, option)
            logger.info(f"JM{jm_id}下载完成")
            
            def find_image_dir(current_dir):
                for root, dirs, files in os.walk(current_dir):
                    image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.heic', '.heif'))]
                    if image_files:
                        return root
                return None
                
            target_dir = find_image_dir(user_download_dir)
            if not target_dir:
                logger.error(f"未找到包含图片的目录")
                return None
                
            logger.info(f"找到图片目录: {target_dir}")
            
            # 使用全局PDF_DIR
            os.makedirs(PDF_DIR, exist_ok=True)
            logger.info(f"PDF目录: {PDF_DIR}")
            
            pdf_path = os.path.join(PDF_DIR, f"{jm_id}.pdf")
            all2PDF(target_dir, PDF_DIR, jm_id)
            
            if os.path.exists(pdf_path):
                logger.info(f"PDF生成成功: {pdf_path}")
                return pdf_path
            else:
                logger.error("PDF文件未生成")
                return None
                
        except Exception as e:
            logger.error(f"PDF下载失败: {e}")
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except Exception as e:
                    logger.error(f"删除PDF文件失败: {e}")
            return None
            
    except Exception as e:
        logger.error(f"PDF下载失败: {e}")
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception as e:
                logger.error(f"删除PDF文件失败: {e}")
        return None
        
    finally:
        # 确保恢复到原始工作目录
        try:
            os.chdir(original_dir)
            logger.info(f"恢复工作目录: {original_dir}")
        except Exception as e:
            logger.error(f"恢复工作目录失败: {e}")

def release_file(file_path: str) -> bool:
    """尝试解除文件占用"""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'open_files']):
            try:
                for file in proc.open_files() or []:
                    if file.path == file_path:
                        logger.info(f"找到占用文件的进程: {proc.name()} (PID: {proc.pid})")
                        proc.kill()
                        logger.info(f"已终止进程: {proc.name()} (PID: {proc.pid})")
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False
    except Exception as e:
        logger.error(f"解除文件占用失败: {e}")
        return False

async def cleanup_user_files(user_id: str, jm_id: str):
    try:
        # 清理用户下载目录
        user_download_dir = os.path.join(os.getcwd(), DOWNLOAD_DIR, str(user_id))
        if os.path.exists(user_download_dir):
            # 删除用户目录下的所有内容
            for item in os.listdir(user_download_dir):
                item_path = os.path.join(user_download_dir, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                    logger.info(f"已删除: {item_path}")
                except Exception as e:
                    logger.error(f"删除文件失败 {item_path}: {e}")

        # 清理ZIP目录
        if os.path.exists(ZIP_DIR):
            for item in os.listdir(ZIP_DIR):
                item_path = os.path.join(ZIP_DIR, item)
                try:
                    os.remove(item_path)
                    logger.info(f"已删除: {item_path}")
                except Exception as e:
                    logger.error(f"删除文件失败 {item_path}: {e}")

        # 清理PDF目录
        if os.path.exists(PDF_DIR):
            for item in os.listdir(PDF_DIR):
                item_path = os.path.join(PDF_DIR, item)
                try:
                    os.remove(item_path)
                    logger.info(f"已删除: {item_path}")
                except Exception as e:
                    logger.error(f"删除文件失败 {item_path}: {e}")

        logger.info(f"已清理所有相关文件")
    except Exception as e:
        logger.error(f"清理文件失败: {e}")

async def handle_message(request):
    try:
        data = await request.json()
        logger.info(f"收到消息: {data}")
        
        if data.get('post_type') != 'message' or data.get('message_type') != 'group':
            logger.debug("不是群消息，忽略")
            return web.Response()
        
        message_parts = data.get('message', [])
        if isinstance(message_parts, list):
            message = ''.join(part.get('data', {}).get('text', '') for part in message_parts if part.get('type') == 'text')
        else:
            message = str(message_parts)
        
        message = message.strip()
        group_id = data.get('group_id')
        user_id = data.get('user_id')
        
        logger.info(f"群 {group_id} 用户 {user_id} 发送消息: {message}")
        
        if message in ["/启用jm", "/禁用jm"]:
            logger.info(f"处理管理员命令: {message}")
            await handle_admin_command(message, group_id, user_id)
            return web.Response()
        
        if message == "/帮助":
            logger.info("处理帮助命令")
            await handle_help_command(group_id, user_id)
            return web.Response()
        
        if group_id not in ENABLED_GROUPS:
            logger.info(f"群 {group_id} 未启用JM功能")
            return web.Response()
        
        match = re.match(r'/jm\s+(\d+)', message)
        if not match:
            logger.debug("不是JM下载命令，忽略")
            return
        
        jm_id = match.group(1)
        logger.info(f"开始下载JM{jm_id}")
        
        current_time = time.time()
        if group_id in GROUP_COOLDOWNS:
            remaining_time = int(GROUP_COOLDOWNS[group_id] - current_time)
            if remaining_time > 0:
                hours = remaining_time // 3600
                minutes = (remaining_time % 3600) // 60
                seconds = remaining_time % 60
                
                time_msg = []
                if hours > 0:
                    time_msg.append(f"{hours}小时")
                if minutes > 0:
                    time_msg.append(f"{minutes}分钟")
                if seconds > 0:
                    time_msg.append(f"{seconds}秒")
                
                wait_time = "".join(time_msg)
                logger.info(f"群 {group_id} 在CD中，剩余 {wait_time}")
                await send_group_message(group_id, f"本群需要等待 {wait_time} 后才能再次下载。")
                return web.Response()
        
        await send_group_message(group_id, f"正在发送JM{jm_id}，请稍候...")
        
        try:
            if PDF_ENABLED:
                logger.info("PDF功能已启用，使用PDF发送方式")
                pdf_path = await download_pdf(jm_id, user_id)
                if not pdf_path or not os.path.exists(pdf_path):
                    logger.error("PDF生成失败")
                    await send_group_message(group_id, f"发送JM{jm_id}失败：PDF生成失败。")
                    return web.Response()
                    
                if os.path.getsize(pdf_path) > MAX_ZIP_SIZE:
                    logger.warning(f"PDF文件大小超过限制: {os.path.getsize(pdf_path)} > {MAX_ZIP_SIZE}")
                    await send_group_message(group_id, f"抱歉，文件大小超过限制（{MAX_ZIP_SIZE/1024/1024}MB），无法发送。")
                    os.remove(pdf_path)
                    return web.Response()
                
                logger.info(f"开始上传PDF文件: {pdf_path}")
                data = {
                    "action": "send_group_msg",
                    "params": {
                        "group_id": group_id,
                        "message": [
                            {
                                "type": "file",
                                "data": {
                                    "name": f"【{jm_id}】.pdf",
                                    "file": pdf_path,
                                    "path": f"【{jm_id}】.pdf"
                                }
                            }
                        ]
                    }
                }
                result = await call_onebot_api("send_group_msg", data)
                
                if result:
                    logger.info("PDF文件上传成功")
                    await send_group_message(group_id, f"JM{jm_id}发送完成！")
                    await cleanup_user_files(user_id, jm_id)
                    # 清理控制台日志
                    os.system('cls' if os.name == 'nt' else 'clear')
                    logger.info(f"JM{jm_id}发送完成，已清理控制台日志")
                else:
                    logger.error("PDF文件上传失败")
                    await send_group_message(group_id, f"JM{jm_id}上传失败：上传请求失败。")
                
                GROUP_COOLDOWNS[group_id] = current_time + COOLDOWN
                logger.info(f"群 {group_id} 进入CD，剩余 {COOLDOWN} 秒")
                return web.Response()
            else:
                logger.info("使用ZIP发送方式")
                user_download_dir = os.path.join(os.getcwd(), DOWNLOAD_DIR, str(user_id))
                os.makedirs(user_download_dir, exist_ok=True)
                
                original_dir = os.getcwd()
                
                try:
                    os.chdir(user_download_dir)
                    logger.info(f"切换到用户下载目录: {user_download_dir}")
                    
                    # 使用配置文件创建下载选项
                    option = jmcomic.create_option_by_file('jm-option.yml')
                    logger.info("已加载JM下载配置")
                    
                    # 使用配置选项下载
                    jmcomic.download_album(jm_id, option)
                    logger.info(f"JM{jm_id}下载完成")
                    
                    zip_path = os.path.join(original_dir, ZIP_DIR, f"{jm_id}.zip")
                    inner_zip_path = os.path.join(original_dir, ZIP_DIR, f"{jm_id}_inner.zip")
                    logger.info(f"开始打包JM{jm_id}")
                    
                    password = ZIP_PASSWORD
                    logger.info(f"使用固定密码: {password}")
                    
                    download_path = user_download_dir
                    logger.info(f"下载目录: {download_path}")
                    
                    if not os.path.exists(download_path):
                        logger.error(f"下载目录不存在: {download_path}")
                        await send_group_message(group_id, f"下载JM{jm_id}失败：找不到下载目录。")
                        return
                        
                    os.makedirs(ZIP_DIR, exist_ok=True)
                    
                    with zipfile.ZipFile(inner_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for root, _, files in os.walk(download_path):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.relpath(file_path, download_path)
                                logger.info(f"正在添加文件到内层zip: {file_path}")
                                zipf.write(file_path, arcname)
                    logger.info(f"内层压缩包创建完成: {inner_zip_path}")
                    
                    logger.info(f"正在创建AES加密的外层压缩包: {zip_path}")
                    password_bytes = password.encode('utf-8')
                    with pyzipper.AESZipFile(zip_path, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zipf:
                        logger.info(f"正在设置AES加密密码: {password}")
                        zipf.setpassword(password_bytes)
                        logger.info("正在添加内层压缩包到外层zip")
                        zipf.write(inner_zip_path, f"{jm_id}.zip")
                        logger.info("外层压缩包创建完成")
                    
                    try:
                        with pyzipper.AESZipFile(zip_path) as zipf:
                            logger.info("正在验证压缩包加密")
                            zipf.setpassword(password_bytes)
                            zipf.extractall(path=os.path.join(original_dir, "test_extract"))
                            logger.info("压缩包AES加密验证成功")
                        shutil.rmtree(os.path.join(original_dir, "test_extract"))
                    except Exception as e:
                        logger.error(f"压缩包AES加密验证失败: {e}")
                        raise Exception("压缩包AES加密失败")
                    
                    if not os.path.exists(zip_path):
                        logger.error(f"zip文件创建失败: {zip_path}")
                        await send_group_message(group_id, f"打包JM{jm_id}失败。")
                        return
                        
                    logger.info(f"zip文件创建成功: {zip_path}")
                    
                    if os.path.getsize(zip_path) > MAX_ZIP_SIZE:
                        logger.warning(f"文件大小超过限制: {os.path.getsize(zip_path)} > {MAX_ZIP_SIZE}")
                        await send_group_message(group_id, f"抱歉，文件大小超过限制（{MAX_ZIP_SIZE/1024/1024}MB），无法发送。")
                        return
                    
                    logger.info(f"开始上传文件: {zip_path}")
                    
                    data = {
                        "action": "send_group_msg",
                        "params": {
                            "group_id": group_id,
                            "message": [
                                {
                                    "type": "file",
                                    "data": {
                                        "name": f"密码{password}【{jm_id}】.zip",
                                        "file": zip_path,
                                        "path": f"密码{password}【{jm_id}】.zip"
                                    }
                                }
                            ]
                        }
                    }
                    result = await call_onebot_api("send_group_msg", data)
                    
                    if result:
                        logger.info("文件上传成功")
                        await send_group_message(group_id, f"JM{jm_id}发送完成！")
                        await cleanup_user_files(user_id, jm_id)
                    else:
                        logger.error("文件上传失败")
                        await send_group_message(group_id, f"JM{jm_id}上传失败：上传请求失败。")
                    
                    GROUP_COOLDOWNS[group_id] = current_time + COOLDOWN
                    logger.info(f"群 {group_id} 进入CD，剩余 {COOLDOWN} 秒")
                    
                    logger.info(f"JM{jm_id}处理完成")
                    
                finally:
                    os.chdir(original_dir)
                    logger.info(f"恢复工作目录: {original_dir}")
                    
        except Exception as e:
            logger.error(f"下载JM{jm_id}失败: {e}")
            await send_group_message(group_id, f"下载JM{jm_id}失败，请稍后重试。")
        
        finally:
            try:
                if 'download_path' in locals() and os.path.exists(download_path):
                    shutil.rmtree(download_path)
                if 'zip_path' in locals() and os.path.exists(zip_path):
                    os.remove(zip_path)
            except Exception as e:
                logger.error(f"清理临时文件失败: {e}")
        
        return web.Response()
        
    except Exception as e:
        logger.error(f"处理消息失败: {e}")
        return web.Response()

async def cleanup_task():
    while True:
        try:
            current_time = time.time()
            max_age = 24 * 60 * 60
            
            for item in os.listdir(DOWNLOAD_DIR):
                item_path = os.path.join(DOWNLOAD_DIR, item)
                if os.path.getmtime(item_path) < current_time - max_age:
                    try:
                        if os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                        logger.info(f"已删除过期文件: {item_path}")
                    except Exception as e:
                        logger.error(f"删除过期文件失败: {e}")
            
            for item in os.listdir(ZIP_DIR):
                item_path = os.path.join(ZIP_DIR, item)
                if os.path.getmtime(item_path) < current_time - max_age:
                    try:
                        os.remove(item_path)
                        logger.info(f"已删除过期文件: {item_path}")
                    except Exception as e:
                        logger.error(f"删除过期文件失败: {e}")
            
            await asyncio.sleep(CLEANUP_INTERVAL)
            
        except Exception as e:
            logger.error(f"清理任务失败: {e}")
            await asyncio.sleep(60)

def find_free_port(start_port: int = 10000, max_port: int = 65535) -> int:
    logger.info(f"开始查找可用端口，范围: {start_port}-{max_port}")
    for port in range(start_port, max_port + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                logger.info(f"找到可用端口: {port}")
                return port
        except OSError as e:
            logger.debug(f"端口 {port} 不可用: {e}")
            continue
    raise RuntimeError(f"在端口范围 {start_port}-{max_port} 内没有找到可用端口")

async def init_app():
    app = web.Application()
    
    asyncio.create_task(cleanup_task())
    
    asyncio.create_task(connect_websocket())
    
    return app

async def connect_websocket():
    global ws_client
    
    while True:
        try:
            url = f"ws://{ONEBOT_HOST}:{ONEBOT_PORT}"
            logger.info(f"正在连接WebSocket: {url}")
            
            timeout = ClientTimeout(total=30)
            connector = TCPConnector(ssl=False, force_close=True)
            
            async with ClientSession(timeout=timeout, connector=connector) as session:
                async with session.ws_connect(url) as ws:
                    ws_client = ws
                    logger.info("WebSocket连接成功")
                    
                    if ONEBOT_ACCESS_TOKEN:
                        auth_data = {
                            "type": "auth",
                            "token": ONEBOT_ACCESS_TOKEN
                        }
                        await ws.send_json(auth_data)
                        logger.info("已发送认证信息")
                    
                    async for msg in ws:
                        if msg.type == WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                if "echo" in data:
                                    continue
                                await handle_message_data(data)
                            except json.JSONDecodeError as e:
                                logger.error(f"解析WebSocket消息失败: {e}")
                        elif msg.type == WSMsgType.CLOSED:
                            logger.warning("WebSocket连接已关闭")
                            ws_client = None
                            break
                        elif msg.type == WSMsgType.ERROR:
                            logger.error(f"WebSocket错误: {msg.data}")
                            ws_client = None
                            break
                
        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}")
            ws_client = None
            logger.info("5秒后重试连接...")
            await asyncio.sleep(5)

async def handle_message_data(data: dict):
    try:
        if data.get('post_type') != 'message' or data.get('message_type') != 'group':
            return
        
        message_parts = data.get('message', [])
        if isinstance(message_parts, list):
            message = ''.join(part.get('data', {}).get('text', '') for part in message_parts if part.get('type') == 'text')
        else:
            message = str(message_parts)
        
        message = message.strip()
        group_id = data.get('group_id')
        user_id = data.get('user_id')
        
        logger.info(f"群 {group_id} 用户 {user_id} 发送消息: {message}")
        
        if message in ["/启用jm", "/禁用jm"]:
            logger.info(f"处理管理员命令: {message}")
            await handle_admin_command(message, group_id, user_id)
            return
        
        if message == "/帮助":
            logger.info("处理帮助命令")
            await handle_help_command(group_id, user_id)
            return
        
        if group_id not in ENABLED_GROUPS:
            logger.info(f"群 {group_id} 未启用JM功能")
            return
        
        match = re.match(r'/jm\s+(\d+)', message)
        if not match:
            logger.debug("不是JM下载命令，忽略")
            return
        
        jm_id = match.group(1)
        logger.info(f"开始下载JM{jm_id}")
        
        current_time = time.time()
        if group_id in GROUP_COOLDOWNS:
            remaining_time = int(GROUP_COOLDOWNS[group_id] - current_time)
            if remaining_time > 0:
                hours = remaining_time // 3600
                minutes = (remaining_time % 3600) // 60
                seconds = remaining_time % 60
                
                time_msg = []
                if hours > 0:
                    time_msg.append(f"{hours}小时")
                if minutes > 0:
                    time_msg.append(f"{minutes}分钟")
                if seconds > 0:
                    time_msg.append(f"{seconds}秒")
                
                wait_time = "".join(time_msg)
                logger.info(f"群 {group_id} 在CD中，剩余 {wait_time}")
                await send_group_message(group_id, f"本群需要等待 {wait_time} 后才能再次下载。")
                return
        
        await send_group_message(group_id, f"正在发送JM{jm_id}，请稍候...")
        
        try:
            if PDF_ENABLED:
                logger.info("使用PDF发送方式")
                pdf_path = await download_pdf(jm_id, user_id)
                if not pdf_path or not os.path.exists(pdf_path):
                    logger.error("PDF生成失败")
                    await send_group_message(group_id, f"发送JM{jm_id}失败：PDF生成失败。")
                    return
                    
                if os.path.getsize(pdf_path) > MAX_ZIP_SIZE:
                    logger.warning(f"PDF文件大小超过限制: {os.path.getsize(pdf_path)} > {MAX_ZIP_SIZE}")
                    await send_group_message(group_id, f"抱歉，文件大小超过限制（{MAX_ZIP_SIZE/1024/1024}MB），无法发送。")
                    os.remove(pdf_path)
                    return
                
                logger.info(f"开始上传PDF文件: {pdf_path}")
                data = {
                    "action": "send_group_msg",
                    "params": {
                        "group_id": group_id,
                        "message": [
                            {
                                "type": "file",
                                "data": {
                                    "name": f"【{jm_id}】.pdf",
                                    "file": pdf_path,
                                    "path": f"【{jm_id}】.pdf"
                                }
                            }
                        ]
                    }
                }
                result = await call_onebot_api("send_group_msg", data)
                
                if result:
                    logger.info("PDF文件上传成功")
                    await send_group_message(group_id, f"JM{jm_id}发送完成！")
                    await cleanup_user_files(user_id, jm_id)
                    # 清理控制台日志
                    os.system('cls' if os.name == 'nt' else 'clear')
                    logger.info(f"JM{jm_id}发送完成，已清理控制台日志")
                else:
                    logger.error("PDF文件上传失败")
                    await send_group_message(group_id, f"JM{jm_id}上传失败：上传请求失败。")
                
                GROUP_COOLDOWNS[group_id] = current_time + COOLDOWN
                logger.info(f"群 {group_id} 进入CD，剩余 {COOLDOWN} 秒")
                return
            else:
                logger.info("使用ZIP发送方式")
                user_download_dir = os.path.join(os.getcwd(), DOWNLOAD_DIR, str(user_id))
                os.makedirs(user_download_dir, exist_ok=True)
                
                original_dir = os.getcwd()
                
                try:
                    os.chdir(user_download_dir)
                    logger.info(f"切换到用户下载目录: {user_download_dir}")
                    
                    # 使用配置文件创建下载选项
                    option = jmcomic.create_option_by_file('jm-option.yml')
                    logger.info("已加载JM下载配置")
                    
                    # 使用配置选项下载
                    jmcomic.download_album(jm_id, option)
                    logger.info(f"JM{jm_id}下载完成")
                    
                    zip_path = os.path.join(original_dir, ZIP_DIR, f"{jm_id}.zip")
                    inner_zip_path = os.path.join(original_dir, ZIP_DIR, f"{jm_id}_inner.zip")
                    logger.info(f"开始打包JM{jm_id}")
                    
                    password = ZIP_PASSWORD
                    logger.info(f"使用固定密码: {password}")
                    
                    download_path = user_download_dir
                    logger.info(f"下载目录: {download_path}")
                    
                    if not os.path.exists(download_path):
                        logger.error(f"下载目录不存在: {download_path}")
                        await send_group_message(group_id, f"下载JM{jm_id}失败：找不到下载目录。")
                        return
                        
                    os.makedirs(ZIP_DIR, exist_ok=True)
                    
                    with zipfile.ZipFile(inner_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for root, _, files in os.walk(download_path):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.relpath(file_path, download_path)
                                logger.info(f"正在添加文件到内层zip: {file_path}")
                                zipf.write(file_path, arcname)
                    logger.info(f"内层压缩包创建完成: {inner_zip_path}")
                    
                    logger.info(f"正在创建AES加密的外层压缩包: {zip_path}")
                    password_bytes = password.encode('utf-8')
                    with pyzipper.AESZipFile(zip_path, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zipf:
                        logger.info(f"正在设置AES加密密码: {password}")
                        zipf.setpassword(password_bytes)
                        logger.info("正在添加内层压缩包到外层zip")
                        zipf.write(inner_zip_path, f"{jm_id}.zip")
                        logger.info("外层压缩包创建完成")
                    
                    try:
                        with pyzipper.AESZipFile(zip_path) as zipf:
                            logger.info("正在验证压缩包加密")
                            zipf.setpassword(password_bytes)
                            zipf.extractall(path=os.path.join(original_dir, "test_extract"))
                            logger.info("压缩包AES加密验证成功")
                        shutil.rmtree(os.path.join(original_dir, "test_extract"))
                    except Exception as e:
                        logger.error(f"压缩包AES加密验证失败: {e}")
                        raise Exception("压缩包AES加密失败")
                    
                    if not os.path.exists(zip_path):
                        logger.error(f"zip文件创建失败: {zip_path}")
                        await send_group_message(group_id, f"打包JM{jm_id}失败。")
                        return
                        
                    logger.info(f"zip文件创建成功: {zip_path}")
                    
                    if os.path.getsize(zip_path) > MAX_ZIP_SIZE:
                        logger.warning(f"文件大小超过限制: {os.path.getsize(zip_path)} > {MAX_ZIP_SIZE}")
                        await send_group_message(group_id, f"抱歉，文件大小超过限制（{MAX_ZIP_SIZE/1024/1024}MB），无法发送。")
                        return
                    
                    logger.info(f"开始上传文件: {zip_path}")
                    
                    data = {
                        "action": "send_group_msg",
                        "params": {
                            "group_id": group_id,
                            "message": [
                                {
                                    "type": "file",
                                    "data": {
                                        "name": f"密码{password}【{jm_id}】.zip",
                                        "file": zip_path,
                                        "path": f"密码{password}【{jm_id}】.zip"
                                    }
                                }
                            ]
                        }
                    }
                    result = await call_onebot_api("send_group_msg", data)
                    
                    if result:
                        logger.info("文件上传成功")
                        await send_group_message(group_id, f"JM{jm_id}发送完成！")
                        await cleanup_user_files(user_id, jm_id)
                    else:
                        logger.error("文件上传失败")
                        await send_group_message(group_id, f"JM{jm_id}上传失败：上传请求失败。")
                    
                    GROUP_COOLDOWNS[group_id] = current_time + COOLDOWN
                    logger.info(f"群 {group_id} 进入CD，剩余 {COOLDOWN} 秒")
                    
                    logger.info(f"JM{jm_id}处理完成")
                    
                finally:
                    os.chdir(original_dir)
                    logger.info(f"恢复工作目录: {original_dir}")
                    
        except Exception as e:
            logger.error(f"下载JM{jm_id}失败: {e}")
            await send_group_message(group_id, f"下载JM{jm_id}失败，请稍后重试。")
        
        finally:
            try:
                if 'download_path' in locals() and os.path.exists(download_path):
                    shutil.rmtree(download_path)
                if 'zip_path' in locals() and os.path.exists(zip_path):
                    os.remove(zip_path)
            except Exception as e:
                logger.error(f"清理临时文件失败: {e}")
                
    except Exception as e:
        logger.error(f"处理消息数据失败: {e}")

def check_port(host: str, port: int) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception as e:
        logger.error(f"检查端口失败: {e}")
        return False

async def wait_for_onebot(host: str, port: int, max_retries: int = 30) -> bool:
    logger.info(f"正在等待OneBot服务启动 ({host}:{port})...")
    for i in range(max_retries):
        if check_port(host, port):
            logger.info("OneBot服务已启动")
            return True
        logger.info(f"等待OneBot服务启动中... ({i+1}/{max_retries})")
        await asyncio.sleep(2)
    logger.error("等待OneBot服务超时")
    return False

def generate_random_password(length=8):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def cleanup_all_files():
    try:
        # 清理downloads目录
        if os.path.exists(DOWNLOAD_DIR):
            for item in os.listdir(DOWNLOAD_DIR):
                item_path = os.path.join(DOWNLOAD_DIR, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                    logger.info(f"已删除: {item_path}")
                except Exception as e:
                    logger.error(f"删除文件失败 {item_path}: {e}")

        # 清理zips目录
        if os.path.exists(ZIP_DIR):
            for item in os.listdir(ZIP_DIR):
                item_path = os.path.join(ZIP_DIR, item)
                try:
                    os.remove(item_path)
                    logger.info(f"已删除: {item_path}")
                except Exception as e:
                    logger.error(f"删除文件失败 {item_path}: {e}")

        # 清理pdf目录
        if os.path.exists(PDF_DIR):
            for item in os.listdir(PDF_DIR):
                item_path = os.path.join(PDF_DIR, item)
                try:
                    os.remove(item_path)
                    logger.info(f"已删除: {item_path}")
                except Exception as e:
                    logger.error(f"删除文件失败 {item_path}: {e}")

        logger.info("所有临时文件清理完成")
    except Exception as e:
        logger.error(f"清理文件失败: {e}")

if __name__ == '__main__':
    logger.info("正在清理临时文件...")
    cleanup_all_files()
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            client_port = find_free_port()
            logger.info(f"已选择客户端端口: {client_port}")
            break
        except RuntimeError as e:
            if attempt < max_retries - 1:
                logger.warning(f"第 {attempt + 1} 次尝试失败: {e}")
                logger.info("等待1秒后重试...")
                time.sleep(1)
            else:
                logger.error(f"选择客户端端口失败，已重试 {max_retries} 次")
                sys.exit(1)
    
    logger.info(f"机器人已启动，正在连接go-cqhttp WebSocket ({ONEBOT_HOST}:{ONEBOT_PORT})...")
    web.run_app(init_app(), host=SERVER_HOST, port=client_port)