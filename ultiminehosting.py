import telebot
import os
import subprocess
import threading
import time
import json
import re
import shutil
from telebot import types
from PIL import Image, ImageDraw, ImageFont
import textwrap
import psutil
import datetime
import pytz
import qrcode
import requests
from io import BytesIO
import logging
import pip
import sys
import traceback
import zipfile
import tempfile
import io

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration - USE ENVIRONMENT VARIABLES IN PRODUCTION!
API_TOKEN = os.getenv("BOT_TOKEN", "BOT_TOKEN_HERE")
bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML")

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
MEDIA_DIR = os.path.join(BASE_DIR, 'media')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
TEMP_DIR = os.path.join(BASE_DIR, 'temp')
MODULES_DIR = os.path.join(BASE_DIR, 'modules')

# Create directories if they don't exist
for directory in [UPLOAD_DIR, LOGS_DIR, MEDIA_DIR, BACKUP_DIR, TEMP_DIR, MODULES_DIR]:
    os.makedirs(directory, exist_ok=True)

# Data files
LIMITS_FILE = os.path.join(BASE_DIR, 'limits.json')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')
BROADCAST_HISTORY_FILE = os.path.join(BASE_DIR, 'broadcast_history.json')
MODULES_FILE = os.path.join(BASE_DIR, 'modules.json')

# Admin and maintenance
ADMIN_IDS = [1295542470]  # Replace with your Telegram user ID
MAINTENANCE_MODE = False
WHITELIST = ADMIN_IDS.copy()  # Users who can use bot during maintenance

# Global variables
processes = {}
user_limits = {}
known_users = set()
start_time = time.time()
broadcast_history = []
installed_modules = {}

# Load data from files
def load_data():
    global user_limits, known_users, broadcast_history, installed_modules
    
    try:
        if os.path.exists(LIMITS_FILE):
            with open(LIMITS_FILE, 'r') as f:
                user_limits = json.load(f)
    except Exception as e:
        logger.error(f"Error loading limits: {e}")
        user_limits = {}
    
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r') as f:
                known_users = set(json.load(f))
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        known_users = set()
    
    try:
        if os.path.exists(BROADCAST_HISTORY_FILE):
            with open(BROADCAST_HISTORY_FILE, 'r') as f:
                broadcast_history = json.load(f)
    except Exception as e:
        logger.error(f"Error loading broadcast history: {e}")
        broadcast_history = []
    
    try:
        if os.path.exists(MODULES_FILE):
            with open(MODULES_FILE, 'r') as f:
                installed_modules = json.load(f)
    except Exception as e:
        logger.error(f"Error loading modules: {e}")
        installed_modules = {}

def save_data():
    try:
        with open(LIMITS_FILE, 'w') as f:
            json.dump(user_limits, f)
    except Exception as e:
        logger.error(f"Error saving limits: {e}")
    
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(list(known_users), f)
    except Exception as e:
        logger.error(f"Error saving users: {e}")
    
    try:
        with open(BROADCAST_HISTORY_FILE, 'w') as f:
            json.dump(broadcast_history, f)
    except Exception as e:
        logger.error(f"Error saving broadcast history: {e}")
    
    try:
        with open(MODULES_FILE, 'w') as f:
            json.dump(installed_modules, f)
    except Exception as e:
        logger.error(f"Error saving modules: {e}")

load_data()

# Utility functions
def get_user_dir(user_id):
    return os.path.join(UPLOAD_DIR, str(user_id))

def ensure_user_dir(user_id):
    path = get_user_dir(user_id)
    os.makedirs(path, exist_ok=True)
    return path

def get_limit(user_id):
    return user_limits.get(str(user_id), 2)

def get_running_count(user_id):
    return sum(1 for k in processes if k.startswith(f"{user_id}:"))

def get_uploaded_count(user_id):
    path = get_user_dir(user_id)
    if not os.path.exists(path):
        return 0
    return len([f for f in os.listdir(path) if f.endswith('.py')])

def get_storage_usage(user_id):
    user_dir = get_user_dir(user_id)
    if not os.path.exists(user_dir):
        return 0
    total_size = 0
    for dirpath, _, filenames in os.walk(user_dir):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    return total_size / (1024 * 1024)  # MB

def get_server_stats():
    try:
        cpu = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        uptime = str(datetime.timedelta(seconds=time.time() - start_time))
        return cpu, memory, disk, uptime
    except Exception as e:
        logger.error(f"Error getting server stats: {e}")
        return 0, 0, 0, "Unknown"

def create_image_with_text(text, filename="broadcast_image.jpg"):
    """Create an image with text for broadcast messages"""
    try:
        img = Image.new('RGB', (800, 600), color=(29, 29, 29))  # Dark background
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except:
            font = ImageFont.load_default()
        
        lines = textwrap.wrap(text, width=40)
        y_text = 50
        for line in lines:
            width, height = font.getsize(line)
            d.text(((800 - width) / 2, y_text), line, font=font, fill=(255, 255, 255))
            y_text += height + 10
        
        watermark = "ULTIMINE Hosting"
        d.text((20, 570), watermark, font=font, fill=(200, 200, 200))
        
        img_path = os.path.join(MEDIA_DIR, filename)
        img.save(img_path)
        return img_path
    except Exception as e:
        logger.error(f"Error creating image: {e}")
        return None

def create_qr_code(data, filename="qrcode.png"):
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img_path = os.path.join(TEMP_DIR, filename)
        img.save(img_path)
        return img_path
    except Exception as e:
        logger.error(f"Error creating QR code: {e}")
        return None

def backup_user_data(user_id):
    try:
        user_dir = get_user_dir(user_id)
        if not os.path.exists(user_dir) or not os.listdir(user_dir):
            return None
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"user_{user_id}_{timestamp}.zip"
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        
        shutil.make_archive(backup_path.replace('.zip', ''), 'zip', user_dir)
        return backup_path
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        return None

def format_time(seconds):
    return str(datetime.timedelta(seconds=int(seconds)))

def sanitize_filename(filename):
    """Sanitize filename to prevent directory traversal"""
    if not filename:
        return None
    filename = os.path.basename(filename)
    if not filename.endswith('.py'):
        filename += '.py'
    return filename

def install_module(module_name, user_id):
    """Install a Python module"""
    try:
        # Check if module is already installed
        if module_name in installed_modules:
            return True, f"Module {module_name} is already installed"
        
        # Install the module
        pip.main(['install', module_name, '--target', MODULES_DIR])
        
        # Add to installed modules
        installed_modules[module_name] = {
            'installed_by': user_id,
            'date': datetime.datetime.now().isoformat()
        }
        save_data()
        
        return True, f"Successfully installed {module_name}"
    except Exception as e:
        logger.error(f"Error installing module {module_name}: {e}")
        return False, f"Failed to install {module_name}: {str(e)}"

def uninstall_module(module_name):
    """Uninstall a Python module"""
    try:
        if module_name not in installed_modules:
            return False, f"Module {module_name} is not installed"
        
        # Uninstall the module
        pip.main(['uninstall', module_name, '-y'])
        
        # Remove from installed modules
        installed_modules.pop(module_name, None)
        save_data()
        
        return True, f"Successfully uninstalled {module_name}"
    except Exception as e:
        logger.error(f"Error uninstalling module {module_name}: {e}")
        return False, f"Failed to uninstall {module_name}: {str(e)}"

def list_installed_modules():
    """List all installed modules"""
    if not installed_modules:
        return "No modules installed"
    
    result = ["<b>Installed Modules:</b>"]
    for module, info in installed_modules.items():
        date = datetime.datetime.fromisoformat(info['date']).strftime("%Y-%m-%d %H:%M")
        result.append(f"• <code>{module}</code> (installed by {info['installed_by']} on {date})")
    
    return "\n".join(result)

# Menu builders
def build_main_menu(user_id):
    limit = get_limit(user_id)
    running = get_running_count(user_id)
    uploaded = get_uploaded_count(user_id)
    usage = get_storage_usage(user_id)
    
    menu = types.InlineKeyboardMarkup(row_width=2)
    
    upload_btn = types.InlineKeyboardButton(
        f"📤 Upload ({uploaded}/{limit})", callback_data='upload_file')
    
    if running >= limit:
        contact_btn = types.InlineKeyboardButton("📞 Contact Admin", url="https://t.me/uditanshu_sarkar")
        menu.add(upload_btn, contact_btn)
    else:
        menu.add(upload_btn)
    
    menu.add(
        types.InlineKeyboardButton("📁 My Files", callback_data='list_files'),
        types.InlineKeyboardButton("📊 Status", callback_data='user_status')
    )
    
    menu.add(
        types.InlineKeyboardButton("▶️ Start Script", callback_data='start_file'),
        types.InlineKeyboardButton("⏹️ Stop Script", callback_data='stop_file')
    )
    
    menu.add(
        types.InlineKeyboardButton("📜 Logs", callback_data='get_log'),
        types.InlineKeyboardButton("❌ Delete", callback_data='delete_file')
    )
    
    menu.add(
        types.InlineKeyboardButton("📦 Backup", callback_data='backup_files'),
        types.InlineKeyboardButton("📦 Restore", callback_data='restore_files')
    )
    
    menu.add(
        types.InlineKeyboardButton("🧩 Modules", callback_data='modules_menu'),
        types.InlineKeyboardButton("ℹ️ Help", callback_data='help')
    )
    
    if user_id in ADMIN_IDS:
        menu.add(types.InlineKeyboardButton("👑 Admin Panel", callback_data='admin_panel'))
    
    return menu

def build_admin_menu():
    menu = types.InlineKeyboardMarkup(row_width=2)
    
    menu.add(
        types.InlineKeyboardButton("📊 Stats", callback_data='admin_stats'),
        types.InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast_menu')
    )
    
    menu.add(
        types.InlineKeyboardButton("👤 User Management", callback_data='user_management'),
        types.InlineKeyboardButton("⚙️ Settings", callback_data='admin_settings')
    )
    
    menu.add(
        types.InlineKeyboardButton("🔙 Main Menu", callback_data='main_menu')
    )
    
    return menu

def build_broadcast_menu():
    menu = types.InlineKeyboardMarkup(row_width=2)
    
    menu.add(
        types.InlineKeyboardButton("📝 Text Broadcast", callback_data='text_broadcast'),
        types.InlineKeyboardButton("🖼️ Image Broadcast", callback_data='image_broadcast')
    )
    
    menu.add(
        types.InlineKeyboardButton("📋 History", callback_data='broadcast_history'),
        types.InlineKeyboardButton("🔙 Back", callback_data='admin_panel')
    )
    
    return menu

def build_broadcast_buttons(buttons_data=None):
    """Build inline buttons for broadcast messages"""
    if not buttons_data:
        return None
    
    try:
        buttons = json.loads(buttons_data)
        if not buttons:
            return None
        
        markup = types.InlineKeyboardMarkup()
        for button in buttons:
            if button.get('url'):
                markup.add(types.InlineKeyboardButton(
                    text=button['text'],
                    url=button['url']
                ))
            elif button.get('callback'):
                markup.add(types.InlineKeyboardButton(
                    text=button['text'],
                    callback_data=button['callback']
                ))
        
        return markup
    except Exception as e:
        logger.error(f"Error parsing broadcast buttons: {e}")
        return None

def build_user_management_menu():
    menu = types.InlineKeyboardMarkup(row_width=2)
    
    menu.add(
        types.InlineKeyboardButton("👤 Add User", callback_data='add_user'),
        types.InlineKeyboardButton("🚫 Remove User", callback_data='remove_user')
    )
    
    menu.add(
        types.InlineKeyboardButton("📈 Set Limits", callback_data='set_limits'),
        types.InlineKeyboardButton("📋 List Users", callback_data='list_users')
    )
    
    menu.add(
        types.InlineKeyboardButton("🔙 Back", callback_data='admin_panel')
    )
    
    return menu

def build_modules_menu():
    menu = types.InlineKeyboardMarkup(row_width=2)
    
    menu.add(
        types.InlineKeyboardButton("📦 Install Module", callback_data='install_module'),
        types.InlineKeyboardButton("🗑️ Uninstall Module", callback_data='uninstall_module')
    )
    
    menu.add(
        types.InlineKeyboardButton("📋 List Modules", callback_data='list_modules'),
        types.InlineKeyboardButton("🔙 Back", callback_data='main_menu')
    )
    
    return menu

# Command handlers with improved usage instructions
@bot.message_handler(commands=['start', 'menu'])
def start(message):
    if MAINTENANCE_MODE and message.from_user.id not in WHITELIST:
        return bot.send_message(message.chat.id, "🔧 Bot is under maintenance. Please try again later.")
    
    try:
        uid = message.from_user.id
        ensure_user_dir(uid)
        known_users.add(uid)
        save_data()
        
        welcome_msg = """
<b>🚀 Welcome to ULTIMINE Hosting</b>

🔹 Host your Python scripts 24/7
🔹 Easy file management
🔹 Real-time logs
🔹 Module installation support

<u>📌 Basic Usage:</u>
1. Upload your Python script with /upload command
2. Start it with /startfile command
3. Check logs with /getlog command

Use the buttons below or type /help for all commands!
"""
        bot.send_message(uid, welcome_msg, reply_markup=build_main_menu(uid))
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        bot.send_message(message.chat.id, "❌ An error occurred. Please try again.")

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
<b>📖 ULTIMINE Hosting Help</b>

<u>👤 User Commands</u>
/start or /menu - Show main menu
/help - Show this help message
/upload - Upload a Python script file
/status - Show your hosting status

<u>📁 File Management</u>
/listfiles - List all your uploaded scripts
/startfile <filename> - Start a script (e.g. /startfile myscript.py)
/stopfile <filename> - Stop a running script
/deletefile <filename> - Delete a script file
/getlog <filename> - Get logs for a script

<u>🛠️ Utilities</u>
/backup - Get backup of all your scripts
/restore - Restore from backup (reply to backup file)
/installmodule <name> - Install a Python module
/uninstallmodule <name> - Uninstall a Python module
/listmodules - List installed modules

<u>👑 Admin Commands</u>
/setlimit <user_id> <limit> - Set user script limit
/adduser <user_id> <limit> - Add new user
/broadcast <message> - Send text broadcast
/broadcastimage - Send image broadcast (reply to image)
/stats - Show bot statistics
/maintenance <on/off> - Toggle maintenance mode
/whitelist <user_id> - Add user to whitelist

<b>⚠️ Note:</b> Replace <filename> with your script name (e.g. bot.py) and <name> with module name (e.g. requests)
"""
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(commands=['status'])
def status_command(message):
    try:
        uid = message.from_user.id
        running = get_running_count(uid)
        limit = get_limit(uid)
        uploaded = get_uploaded_count(uid)
        usage = get_storage_usage(uid)
        cpu, mem, disk, uptime = get_server_stats()
        
        status_text = f"""
<b>📊 Your Hosting Status</b>
📂 Files Uploaded: {uploaded}/{limit}
▶️ Running Scripts: {running}/{limit}
💾 Storage Used: {usage:.2f} MB

<b>🖥️ Server Status</b>
CPU Usage: {cpu}%
Memory Usage: {mem}%
Disk Usage: {disk}%
Uptime: {uptime}

<u>💡 Usage Tip:</u>
Use /listfiles to see all your scripts
Use /startfile <filename> to run a script
"""
        bot.send_message(uid, status_text)
    except Exception as e:
        logger.error(f"Error in status command: {e}")
        bot.send_message(message.chat.id, "❌ Could not get status. Please try again.")

@bot.message_handler(commands=['upload'])
def upload_command(message):
    if MAINTENANCE_MODE and message.from_user.id not in WHITELIST:
        return
    
    try:
        uid = str(message.chat.id)
        current = get_uploaded_count(uid)
        limit = get_limit(uid)
        
        if current >= limit:
            return bot.reply_to(message, f"🚫 You've reached your limit of {limit} scripts. Delete some files first.")
        
        instructions = f"""
📤 <b>How to upload a script:</b>
1. Send me your Python file (.py extension)
2. Max file size: 20MB
3. Current uploads: {current}/{limit}

<u>⚠️ Important:</u>
- Only standard Python scripts are allowed
- Scripts must have .py extension
- No malicious code allowed
"""
        bot.reply_to(message, instructions)
    except Exception as e:
        logger.error(f"Error in upload command: {e}")
        bot.reply_to(message, "❌ Failed to process upload request. Please try again.")

@bot.message_handler(commands=['listfiles'])
def list_files_command(message):
    try:
        uid = message.chat.id
        user_dir = os.path.join(UPLOAD_DIR, str(uid))
        running_scripts = [k.split(':')[1] for k in processes if k.startswith(f"{uid}:")]
        
        if not os.path.exists(user_dir) or not os.listdir(user_dir):
            return bot.reply_to(message, "📁 You don't have any files yet. Use /upload to add scripts.")
        
        files = os.listdir(user_dir)
        response = ["<b>📁 Your Script Files</b>\n"]
        
        for file in files:
            if file.endswith('.py'):
                status = "🟢 Running" if file in running_scripts else "⚪ Stopped"
                size = os.path.getsize(os.path.join(user_dir, file)) / 1024  # KB
                response.append(f"• <code>{file}</code> - {status} ({size:.1f} KB)")
        
        response.append("\n<u>💡 Usage:</u>")
        response.append("To start: /startfile filename.py")
        response.append("To stop: /stopfile filename.py")
        response.append("To delete: /deletefile filename.py")
        
        bot.reply_to(message, "\n".join(response))
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        bot.reply_to(message, "❌ Failed to list files. Please try again.")

@bot.message_handler(commands=['startfile'])
def start_file_command(message):
    if MAINTENANCE_MODE and message.from_user.id not in WHITELIST:
        return
    
    try:
        if len(message.text.split()) < 2:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /startfile filename.py

<u>Example:</u>
/startfile mybot.py

<u>Note:</u>
- Script must be uploaded first
- Check available scripts with /listfiles
- You can run up to {limit} scripts simultaneously
""".format(limit=get_limit(message.from_user.id)))
        
        filename = sanitize_filename(message.text.split()[1])
        if not filename:
            return bot.reply_to(message, "❌ Invalid filename. Must end with .py")
        
        uid = str(message.chat.id)
        path = os.path.join(UPLOAD_DIR, uid, filename)
        key = f"{uid}:{filename}"
        
        if not os.path.exists(path):
            return bot.reply_to(message, f"""
❌ File not found: {filename}

<u>What to do:</u>
1. Check spelling with /listfiles
2. Upload the file with /upload
""")
        
        if key in processes:
            return bot.reply_to(message, f"⚠️ Script is already running: {filename}")
        
        if get_running_count(uid) >= get_limit(uid):
            return bot.reply_to(message, f"""
🚫 Script limit reached ({get_limit(uid)})

<u>Options:</u>
1. Stop other scripts with /stopfile
2. Ask admin to increase your limit
""")
        
        def run_script():
            log_file = os.path.join(LOGS_DIR, f"{uid}_{filename}.log")
            
            env = os.environ.copy()
            env['PYTHONPATH'] = MODULES_DIR
            
            with open(log_file, 'w') as f:
                proc = subprocess.Popen(
                    ['python', path],
                    stdout=f,
                    stderr=f,
                    env=env
                )
                
                processes[key] = {
                    'process': proc,
                    'start': time.time(),
                    'log_file': log_file
                }
                
                try:
                    proc.wait(timeout=3600)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                finally:
                    processes.pop(key, None)
        
        threading.Thread(target=run_script).start()
        
        bot.reply_to(message, f"""
✅ Started script: <code>{filename}</code>

<u>Next steps:</u>
- Check logs with /getlog {filename.replace('.py', '')}
- Stop with /stopfile {filename}
""")
    except Exception as e:
        logger.error(f"Error starting file: {e}")
        bot.reply_to(message, "❌ Failed to start script. Please try again.")

@bot.message_handler(commands=['stopfile'])
def stop_file_command(message):
    try:
        if len(message.text.split()) < 2:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /stopfile filename.py

<u>Example:</u>
/stopfile mybot.py

<u>Note:</u>
- Use /listfiles to see running scripts
""")
        
        filename = sanitize_filename(message.text.split()[1])
        if not filename:
            return bot.reply_to(message, "❌ Invalid filename. Must end with .py")
        
        key = f"{message.chat.id}:{filename}"
        
        if key not in processes:
            return bot.reply_to(message, f"""
⚠️ Script isn't running: {filename}

<u>Possible reasons:</u>
1. Script already stopped
2. Never started
3. Crashed unexpectedly

Check status with /listfiles
""")
        
        proc_info = processes[key]
        proc_info['process'].terminate()
        runtime = time.time() - proc_info['start']
        processes.pop(key, None)
        
        bot.reply_to(message, f"""
✅ Stopped script: <code>{filename}</code>
⏱️ Runtime: {format_time(runtime)}

<u>Note:</u>
You can restart it with /startfile {filename}
""")
    except Exception as e:
        logger.error(f"Error stopping file: {e}")
        bot.reply_to(message, "❌ Failed to stop script. Please try again.")

@bot.message_handler(commands=['deletefile'])
def delete_file_command(message):
    try:
        if len(message.text.split()) < 2:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /deletefile filename.py

<u>Example:</u>
/deletefile oldbot.py

<u>Warning:</u>
This will permanently delete the file!
""")
        
        filename = sanitize_filename(message.text.split()[1])
        if not filename:
            return bot.reply_to(message, "❌ Invalid filename. Must end with .py")
        
        uid = message.chat.id
        py_path = os.path.join(UPLOAD_DIR, str(uid), filename)
        log_path = os.path.join(LOGS_DIR, f"{uid}_{filename}.log")
        key = f"{uid}:{filename}"
        
        # Stop if running
        if key in processes:
            processes[key]['process'].terminate()
            processes.pop(key, None)
        
        # Delete files
        deleted = []
        if os.path.exists(py_path):
            os.remove(py_path)
            deleted.append(filename)
        
        if os.path.exists(log_path):
            os.remove(log_path)
            deleted.append(f"{filename}.log")
        
        if deleted:
            bot.reply_to(message, f"""
✅ Successfully deleted:
{', '.join(deleted)}

<u>Note:</u>
You can upload a new version with /upload
""")
        else:
            bot.reply_to(message, f"""
❌ File not found: {filename}

<u>What to do:</u>
1. Check spelling with /listfiles
2. File may already be deleted
""")
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        bot.reply_to(message, "❌ Failed to delete file. Please try again.")

@bot.message_handler(commands=['getlog'])
def get_log_command(message):
    try:
        if len(message.text.split()) < 2:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /getlog filename.py

<u>Example:</u>
/getlog mybot.py

<u>Note:</u>
- Shows last 4096 characters if log is large
- Empty if script hasn't produced output
""")
        
        filename = sanitize_filename(message.text.split()[1])
        if not filename:
            return bot.reply_to(message, "❌ Invalid filename. Must end with .py")
        
        log_path = os.path.join(LOGS_DIR, f"{message.chat.id}_{filename}.log")
        
        if os.path.exists(log_path):
            with open(log_path, 'rb') as log_file:
                if os.path.getsize(log_path) > 4096:
                    bot.send_message(message.chat.id, "⚠️ Log is large, sending as file:")
                bot.send_document(message.chat.id, log_file, caption=f"📜 Logs for {filename}")
        else:
            bot.reply_to(message, f"""
❌ No logs found for: {filename}

<u>Possible reasons:</u>
1. Script never started
2. No output produced yet
3. Logs were cleared
""")
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        bot.reply_to(message, "❌ Failed to get logs. Please try again.")

@bot.message_handler(commands=['backup'])
def backup_command(message):
    try:
        uid = message.from_user.id
        backup_path = backup_user_data(uid)
        
        if backup_path:
            with open(backup_path, 'rb') as backup_file:
                bot.send_document(uid, backup_file, caption="📦 Here's your backup!")
        else:
            bot.send_message(uid, "❌ No files to backup.")
    except Exception as e:
        logger.error(f"Error in backup command: {e}")
        bot.send_message(message.chat.id, "❌ Failed to create backup. Please try again.")

@bot.message_handler(commands=['restore'])
def restore_command(message):
    try:
        if not (message.reply_to_message and message.reply_to_message.document):
            return bot.reply_to(message, """
❌ <b>Usage:</b> Reply to a backup file with /restore

<u>Example:</u>
1. Upload your backup.zip file
2. Reply to it with /restore

<u>Note:</u>
- Only .zip files from this bot are supported
- This will overwrite existing files
""")
        
        uid = message.from_user.id
        file = message.reply_to_message.document
        
        if not file.file_name.endswith('.zip'):
            return bot.reply_to(message, "❌ Only .zip backup files are allowed.")
        
        # Download the file
        file_info = bot.get_file(file.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Extract to user directory
        user_dir = ensure_user_dir(uid)
        with zipfile.ZipFile(io.BytesIO(downloaded_file), 'r') as zip_ref:
            zip_ref.extractall(user_dir)
        
        bot.reply_to(message, "✅ Backup restored successfully!")
    except Exception as e:
        logger.error(f"Error in restore command: {e}")
        bot.reply_to(message, "❌ Failed to restore backup. Please try again.")

@bot.message_handler(commands=['installmodule'])
def install_module_command(message):
    if MAINTENANCE_MODE and message.from_user.id not in WHITELIST:
        return
    
    try:
        if len(message.text.split()) < 2:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /installmodule module_name

<u>Example:</u>
/installmodule requests

<u>Note:</u>
- Installs from PyPI
- Requires admin approval for some modules
""")
        
        module_name = message.text.split()[1].strip()
        uid = message.from_user.id
        
        success, result = install_module(module_name, uid)
        bot.reply_to(message, result)
    except Exception as e:
        logger.error(f"Error in installmodule command: {e}")
        bot.reply_to(message, "❌ Failed to install module. Please try again.")

@bot.message_handler(commands=['uninstallmodule'])
def uninstall_module_command(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        if len(message.text.split()) < 2:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /uninstallmodule module_name

<u>Example:</u>
/uninstallmodule requests

<u>Warning:</u>
This will remove the module for all users!
""")
        
        module_name = message.text.split()[1].strip()
        
        success, result = uninstall_module(module_name)
        bot.reply_to(message, result)
    except Exception as e:
        logger.error(f"Error in uninstallmodule command: {e}")
        bot.reply_to(message, "❌ Failed to uninstall module. Please try again.")

@bot.message_handler(commands=['listmodules'])
def list_modules_command(message):
    try:
        modules_list = list_installed_modules()
        bot.reply_to(message, modules_list)
    except Exception as e:
        logger.error(f"Error in listmodules command: {e}")
        bot.reply_to(message, "❌ Failed to list modules. Please try again.")

# Admin commands
@bot.message_handler(commands=['setlimit', 'adduser'])
def admin_set_limit(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 3:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /setlimit user_id limit

<u>Example:</u>
/setlimit 123456789 5

<u>Note:</u>
- Sets how many scripts a user can run simultaneously
- Use /adduser to create new users
""")
        
        uid = parts[1]
        limit = int(parts[2])
        
        user_limits[str(uid)] = limit
        known_users.add(int(uid))
        save_data()
        
        bot.reply_to(message, f"✅ Set user {uid} limit to {limit}")
    except Exception as e:
        logger.error(f"Error setting limit: {e}")
        bot.reply_to(message, "❌ Failed to set limit. Usage: /setlimit <user_id> <limit>")

@bot.message_handler(commands=['stats'])
def admin_stats(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        total_users = len(known_users)
        active_users = sum(1 for uid in known_users if get_uploaded_count(uid) > 0)
        running_scripts = len(processes)
        cpu, mem, disk, uptime = get_server_stats()
        
        stats_text = f"""
<b>📊 Bot Statistics</b>
👥 Total users: {total_users}
👤 Active users: {active_users}
▶️ Running scripts: {running_scripts}
⏱️ Uptime: {uptime}

<b>🖥️ Server Stats</b>
CPU: {cpu}%
Memory: {mem}%
Disk: {disk}%
"""
        bot.reply_to(message, stats_text)
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        bot.reply_to(message, "❌ Failed to get stats. Please try again.")

@bot.message_handler(commands=['broadcast'])
def broadcast_text(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        # Check if this is a reply to a command with buttons
        if message.reply_to_message and message.reply_to_message.text.startswith("Enter broadcast buttons"):
            try:
                buttons_data = message.text
                json.loads(buttons_data)  # Validate JSON
                
                # Get the original broadcast message
                original_msg = message.reply_to_message.reply_to_message
                if not original_msg:
                    return bot.reply_to(message, "❌ Original broadcast message not found.")
                
                msg = original_msg.text.replace("/broadcast", "").strip()
                parse_mode = "HTML" if re.search(r'<[a-z][\s\S]*>', msg) else None
                
                markup = build_broadcast_buttons(buttons_data)
                
                sent = 0
                failed = 0
                for uid in known_users:
                    try:
                        bot.send_message(uid, f"📢 <b>Announcement</b>\n\n{msg}", 
                                       parse_mode=parse_mode, 
                                       reply_markup=markup)
                        sent += 1
                        time.sleep(0.1)  # Rate limiting
                    except Exception as e:
                        logger.error(f"Error broadcasting to {uid}: {e}")
                        failed += 1
                
                # Save to history
                broadcast_history.append({
                    'type': 'text',
                    'content': msg,
                    'buttons': buttons_data,
                    'date': datetime.datetime.now().isoformat(),
                    'sent': sent,
                    'failed': failed
                })
                save_data()
                
                return bot.reply_to(message, f"✅ Broadcast with buttons complete!\nSent: {sent}\nFailed: {failed}")
            except json.JSONDecodeError:
                return bot.reply_to(message, "❌ Invalid JSON format for buttons. Please try again.")
        
        # Normal broadcast without buttons
        msg = message.text.replace("/broadcast", "").strip()
        if not msg:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /broadcast message

<u>Example:</u>
/broadcast Server maintenance in 1 hour!

<u>Note:</u>
- Supports HTML formatting
- Will be sent to all users
""")
        
        # Ask if user wants to add buttons
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Yes", callback_data=f"add_buttons:{msg}"),
            types.InlineKeyboardButton("No", callback_data=f"broadcast_now:{msg}")
        )
        
        bot.reply_to(message, "Do you want to add inline buttons to this broadcast?", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in broadcast: {e}")
        bot.reply_to(message, "❌ Failed to broadcast. Please try again.")

@bot.message_handler(commands=['broadcastimage'])
def broadcast_image(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        if not (message.reply_to_message and message.reply_to_message.photo):
            return bot.reply_to(message, """
❌ <b>Usage:</b> Reply to an image with /broadcastimage caption

<u>Example:</u>
1. Send an image
2. Reply to it with /broadcastimage Hello everyone!
""")
        
        caption = message.text.replace("/broadcastimage", "").strip()
        if not caption:
            caption = "💖"
        
        # Ask if user wants to add buttons
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Yes", callback_data=f"add_buttons_image:{caption}"),
            types.InlineKeyboardButton("No", callback_data=f"broadcast_image_now:{caption}")
        )
        
        bot.reply_to(message, "Do you want to add inline buttons to this broadcast?", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in image broadcast: {e}")
        bot.reply_to(message, "❌ Failed to broadcast image. Please try again.")

@bot.message_handler(commands=['maintenance'])
def maintenance_mode(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        if len(message.text.split()) < 2:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /maintenance <on/off>

<u>Example:</u>
/maintenance on

<u>Note:</u>
- When on, only whitelisted users can use the bot
- Use /whitelist to add users
""")
        
        mode = message.text.split()[1].lower()
        global MAINTENANCE_MODE
        
        if mode == 'on':
            MAINTENANCE_MODE = True
            bot.reply_to(message, "🔧 Maintenance mode ENABLED")
        elif mode == 'off':
            MAINTENANCE_MODE = False
            bot.reply_to(message, "✅ Maintenance mode DISABLED")
        else:
            bot.reply_to(message, "❌ Usage: /maintenance <on/off>")
    except Exception as e:
        logger.error(f"Error setting maintenance mode: {e}")
        bot.reply_to(message, "❌ Failed to set maintenance mode. Please try again.")

@bot.message_handler(commands=['whitelist'])
def whitelist_user(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        if len(message.text.split()) < 2:
            return bot.reply_to(message, """
❌ <b>Usage:</b> /whitelist user_id

<u>Example:</u>
/whitelist 123456789

<u>Note:</u>
- Whitelisted users can use bot during maintenance
- Admins are automatically whitelisted
""")
        
        uid = int(message.text.split()[1])
        WHITELIST.append(uid)
        bot.reply_to(message, f"✅ Added {uid} to whitelist")
    except Exception as e:
        logger.error(f"Error adding to whitelist: {e}")
        bot.reply_to(message, "❌ Failed to add to whitelist. Usage: /whitelist <user_id>")

# Callback handlers
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        uid = call.from_user.id
        data = call.data
        
        if data == 'main_menu':
            bot.edit_message_text(
                chat_id=uid,
                message_id=call.message.message_id,
                text="Main Menu",
                reply_markup=build_main_menu(uid)
            )
        
        elif data == 'upload_file':
            current = get_uploaded_count(uid)
            limit = get_limit(uid)
            bot.send_message(uid, f"📤 Send your Python (.py) file now\nUploaded: {current}/{limit}")
        
        elif data == 'list_files':
            list_files_command(call.message)
        
        elif data == 'user_status':
            status_command(call.message)
        
        elif data == 'start_file':
            bot.send_message(uid, "Send /startfile <filename.py> to start a script")
        
        elif data == 'stop_file':
            bot.send_message(uid, "Send /stopfile <filename.py> to stop a script")
        
        elif data == 'get_log':
            bot.send_message(uid, "Send /getlog <filename.py> to get logs")
        
        elif data == 'delete_file':
            bot.send_message(uid, "Send /deletefile <filename.py> to delete a file")
        
        elif data == 'backup_files':
            backup_command(call.message)
        
        elif data == 'restore_files':
            bot.send_message(uid, "Reply to a backup file with /restore command")
        
        elif data == 'modules_menu':
            bot.edit_message_text(
                chat_id=uid,
                message_id=call.message.message_id,
                text="🧩 Modules Management",
                reply_markup=build_modules_menu())
        
        elif data == 'install_module':
            bot.send_message(uid, "Send /installmodule <module_name> to install a Python module")
        
        elif data == 'uninstall_module':
            bot.send_message(uid, "Send /uninstallmodule <module_name> to uninstall a Python module")
        
        elif data == 'list_modules':
            list_modules_command(call.message)
        
        elif data == 'help':
            help_command(call.message)
        
        elif data == 'admin_panel' and uid in ADMIN_IDS:
            bot.edit_message_text(
                chat_id=uid,
                message_id=call.message.message_id,
                text="👑 Admin Panel",
                reply_markup=build_admin_menu())
        
        elif data == 'admin_stats' and uid in ADMIN_IDS:
            admin_stats(call.message)
        
        elif data == 'admin_broadcast_menu' and uid in ADMIN_IDS:
            bot.edit_message_text(
                chat_id=uid,
                message_id=call.message.message_id,
                text="📢 Broadcast Menu",
                reply_markup=build_broadcast_menu())
        
        elif data == 'text_broadcast' and uid in ADMIN_IDS:
            bot.send_message(uid, "Send your broadcast message with /broadcast command")
        
        elif data == 'image_broadcast' and uid in ADMIN_IDS:
            bot.send_message(uid, "Reply to an image with /broadcastimage command")
        
        elif data == 'broadcast_history' and uid in ADMIN_IDS:
            if not broadcast_history:
                bot.send_message(uid, "No broadcast history yet.")
                return
            
            history_text = ["<b>📋 Broadcast History</b>"]
            for i, item in enumerate(reversed(broadcast_history[-10:]), 1:
                date = datetime.datetime.fromisoformat(item['date']).strftime("%Y-%m-%d %H:%M")
                
                if item['type'] == 'text':
                    preview = item['content'][:30] + ("..." if len(item['content']) > 30 else "")
                    history_text.append(f"{i}. 📝 {date}\n{preview}\nSent: {item['sent']} | Failed: {item['failed']}")
                else:
                    history_text.append(f"{i}. 🖼️ {date}\nCaption: {item['caption']}\nSent: {item['sent']} | Failed: {item['failed']}")
            
            bot.send_message(uid, "\n\n".join(history_text))
        
        elif data == 'user_management' and uid in ADMIN_IDS:
            bot.edit_message_text(
                chat_id=uid,
                message_id=call.message.message_id,
                text="👤 User Management",
                reply_markup=build_user_management_menu())
        
        elif data == 'add_user' and uid in ADMIN_IDS:
            bot.send_message(uid, "Send /adduser <user_id> <limit> to add a new user")
        
        elif data == 'remove_user' and uid in ADMIN_IDS:
            bot.send_message(uid, "Not implemented yet")
        
        elif data == 'set_limits' and uid in ADMIN_IDS:
            bot.send_message(uid, "Send /setlimit <user_id> <limit> to change user limits")
        
        elif data == 'list_users' and uid in ADMIN_IDS:
            users_list = ["<b>👥 Registered Users</b>"]
            for user in known_users:
                limit = get_limit(user)
                running = get_running_count(user)
                users_list.append(f"• ID: {user} | Limit: {limit} | Running: {running}")
            
            bot.send_message(uid, "\n".join(users_list))
        
        elif data.startswith('add_buttons:') and uid in ADMIN_IDS:
            msg = data.split(':', 1)[1]
            bot.send_message(uid, "Enter broadcast buttons in JSON format (reply to this message):\n\n"
                              "Example:\n"
                              '[{"text": "Visit Website", "url": "https://example.com"}]\n\n'
                              'Available button types:\n'
                              '- url: Opens a URL\n'
                              '- callback: Sends a callback when pressed',
                              reply_to_message_id=call.message.message_id)
        
        elif data.startswith('broadcast_now:') and uid in ADMIN_IDS:
            msg = data.split(':', 1)[1]
            parse_mode = "HTML" if re.search(r'<[a-z][\s\S]*>', msg) else None
            
            sent = 0
            failed = 0
            for uid in known_users:
                try:
                    bot.send_message(uid, f"📢 <b>Announcement</b>\n\n{msg}", parse_mode=parse_mode)
                    sent += 1
                    time.sleep(0.1)  # Rate limiting
                except Exception as e:
                    logger.error(f"Error broadcasting to {uid}: {e}")
                    failed += 1
            
            # Save to history
            broadcast_history.append({
                'type': 'text',
                'content': msg,
                'date': datetime.datetime.now().isoformat(),
                'sent': sent,
                'failed': failed
            })
            save_data()
            
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"✅ Broadcast complete!\nSent: {sent}\nFailed: {failed}")
        
        elif data.startswith('add_buttons_image:') and uid in ADMIN_IDS:
            caption = data.split(':', 1)[1]
            bot.send_message(uid, "Enter broadcast buttons in JSON format (reply to this message):\n\n"
                              "Example:\n"
                              '[{"text": "Visit Website", "url": "https://example.com"}]\n\n'
                              'Available button types:\n'
                              '- url: Opens a URL\n'
                              '- callback: Sends a callback when pressed',
                              reply_to_message_id=call.message.message_id)
        
        elif data.startswith('broadcast_image_now:') and uid in ADMIN_IDS:
            caption = data.split(':', 1)[1]
            
            # Get the original image message
            original_msg = call.message.reply_to_message
            if not (original_msg and original_msg.photo):
                return bot.send_message(uid, "❌ Original image not found.")
            
            # Download the image
            file_info = bot.get_file(original_msg.photo[-1].file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            sent = 0
            failed = 0
            for uid in known_users:
                try:
                    bot.send_photo(uid, downloaded_file, caption=caption)
                    sent += 1
                    time.sleep(0.1)  # Rate limiting
                except Exception as e:
                    logger.error(f"Error broadcasting image to {uid}: {e}")
                    failed += 1
            
            # Save to history
            broadcast_history.append({
                'type': 'image',
                'caption': caption,
                'date': datetime.datetime.now().isoformat(),
                'sent': sent,
                'failed': failed
            })
            save_data()
            
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"✅ Image broadcast complete!\nSent: {sent}\nFailed: {failed}")
    
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        bot.send_message(call.message.chat.id, "❌ An error occurred. Please try again.")

# Error handler
@bot.message_handler(func=lambda message: True)
def unknown_command(message):
    if message.text.startswith('/'):
        bot.reply_to(message, "❌ Unknown command. Use /help for available commands.")
    elif not MAINTENANCE_MODE or message.from_user.id in WHITELIST:
        bot.reply_to(message, "ℹ️ Use the menu buttons or commands to interact with me.")

# Start the bot
if __name__ == '__main__':
    logger.info("🤖 ULTIMINE Hosting Bot is starting...")
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise