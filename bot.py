import os
import logging
import sqlite3
import asyncio
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN not set!")
    exit(1)

# Admin configuration
ADMIN_IDS = {6503449202, 7573908933, 1388128653}  # Replace with your actual admin IDs
XP_PER_APPROVAL = 20
APPROVALS_NEEDED = 15

# Health check server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        elif self.path == '/ping':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'PONG')
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'EliteXPBot is running!')
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
    logger.info("🩺 Health server running on port 8000")
    server.serve_forever()

# Database setup
def init_db():
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            daily_xp INTEGER DEFAULT 0,
            comment_xp INTEGER DEFAULT 0,
            proof_xp INTEGER DEFAULT 0,
            last_active TIMESTAMP,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approvals (
            user_id INTEGER,
            approval_count INTEGER DEFAULT 0,
            last_approval TIMESTAMP,
            PRIMARY KEY (user_id)
        )
    ''')
    
    # Insert admin users
    for admin_id in ADMIN_IDS:
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, first_name, is_admin, last_active)
            VALUES (?, 'Admin', TRUE, ?)
        ''', (admin_id, datetime.now()))
    
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized with admin users!")

init_db()

def get_user(user_id):
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return {
            'user_id': user[0], 'username': user[1], 'first_name': user[2],
            'last_name': user[3], 'xp': user[4], 'level': user[5],
            'daily_xp': user[6], 'comment_xp': user[7], 'proof_xp': user[8],
            'last_active': user[9], 'is_admin': user[10], 'created_at': user[11]
        }
    return None

def create_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users 
        (user_id, username, first_name, last_name, xp, level, last_active) 
        VALUES (?, ?, ?, ?, 0, 1, ?)
    ''', (user_id, username, first_name, last_name, datetime.now()))
    conn.commit()
    conn.close()

def update_user_xp(user_id, xp_to_add, xp_type="general"):
    user = get_user(user_id)
    if not user: return None
    
    new_xp = user['xp'] + xp_to_add
    
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    
    if xp_type == "daily":
        new_daily_xp = user['daily_xp'] + xp_to_add
        cursor.execute('UPDATE users SET xp = ?, daily_xp = ?, last_active = ? WHERE user_id = ?',
                      (new_xp, new_daily_xp, datetime.now(), user_id))
    elif xp_type == "comment":
        new_comment_xp = user['comment_xp'] + xp_to_add
        cursor.execute('UPDATE users SET xp = ?, comment_xp = ?, last_active = ? WHERE user_id = ?',
                      (new_xp, new_comment_xp, datetime.now(), user_id))
    elif xp_type == "proof":
        new_proof_xp = user['proof_xp'] + xp_to_add
        cursor.execute('UPDATE users SET xp = ?, proof_xp = ?, last_active = ? WHERE user_id = ?',
                      (new_xp, new_proof_xp, datetime.now(), user_id))
    else:
        cursor.execute('UPDATE users SET xp = ?, last_active = ? WHERE user_id = ?',
                      (new_xp, datetime.now(), user_id))
    
    conn.commit()
    conn.close()
    
    return new_xp

def get_all_users():
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, first_name, xp, last_active FROM users ORDER BY xp DESC')
    users = cursor.fetchall()
    conn.close()
    return users

def get_approval_count(user_id):
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT approval_count FROM approvals WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def add_approval(user_id):
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO approvals (user_id, approval_count, last_approval)
        VALUES (?, COALESCE((SELECT approval_count FROM approvals WHERE user_id = ?), 0) + 1, ?)
    ''', (user_id, user_id, datetime.now()))
    
    conn.commit()
    conn.close()
    
    # Award XP for approval
    update_user_xp(user_id, XP_PER_APPROVAL, "proof")

# Bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = f"""
👋 Welcome {user.first_name} to EliteXPBot! 🎮

🤖 **EliteXP Bot Features:**
• Earn XP through various activities
• Daily bonuses and rewards  
• Leaderboard competition
• Admin management system

📊 **User Commands:**
/profile - Check your stats
/leaderboard - See top users

👑 **Admin Commands:**
/addxp - Add XP to user
/checkusers - View all users
/resetlinks - Reset approval links

🏆 Compete and climb the leaderboard!
    """
    
    await update.message.reply_text(welcome_text)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_user(user.id)
    
    if not user_data:
        create_user(user.id, user.username, user.first_name, user.last_name)
        user_data = get_user(user.id)
    
    approval_count = get_approval_count(user.id)
    
    profile_text = f"""
📊 **XP Summary for {user.first_name}**

💎 Daily XP: {user_data['daily_xp']}
💬 Comment XP: {user_data['comment_xp']}
✅ Proof XP: {user_data['proof_xp']}
🏆 Total XP: {user_data['xp']}

✅ Approvals: {approval_count}/{APPROVALS_NEEDED}
📈 XP per Approval: {XP_PER_APPROVAL}

🕒 Last Active: {user_data['last_active']}
    """
    
    await update.message.reply_text(profile_text)

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    
    if not users:
        await update.message.reply_text("📊 No users yet!")
        return
    
    leaderboard_text = "🏆 **EliteXP Leaderboard** 🏆\n\n"
    
    for i, (user_id, username, first_name, xp, last_active) in enumerate(users[:10], 1):
        display_name = first_name or username or f"User {user_id}"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        leaderboard_text += f"{medal} {display_name} - {xp} XP\n"
    
    await update.message.reply_text(leaderboard_text)

# Admin commands
async def addxp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin access required!")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /addxp <user_id> <xp_amount>")
        return
    
    try:
        target_user_id = int(context.args[0])
        xp_amount = int(context.args[1])
        
        target_user = get_user(target_user_id)
        if not target_user:
            await update.message.reply_text("❌ User not found!")
            return
        
        new_xp = update_user_xp(target_user_id, xp_amount)
        await update.message.reply_text(f"✅ Added {xp_amount} XP to user {target_user['first_name']}\nNew total: {new_xp} XP")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID or XP amount!")

async def checkusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin access required!")
        return
    
    users = get_all_users()
    active_threshold = datetime.now() - timedelta(days=7)
    
    active_users = [u for u in users if datetime.fromisoformat(u[4]) > active_threshold]
    total_xp = sum(user[3] for user in users)
    
    debug_text = f"""
🔍 **DEBUG INFORMATION:**

🆔 Telegram says your ID: {user.id}
👤 Username: {user.username or 'N/A'}
📝 First name: {user.first_name or 'N/A'}
👑 Is admin: {user.id in ADMIN_IDS}
📋 Admin IDs in config: {ADMIN_IDS}

📊 ADMIN VIEW: {len(users)} Users | Total XP: {total_xp}

"""
    
    for i, (user_id, username, first_name, xp, last_active) in enumerate(users, 1):
        debug_text += f"{i}. {first_name or username} (ID: {user_id}) - {xp} XP\n"
    
    debug_text += f"""
📊 Bot Statistics 👑:

👥 Total Users: {len(users)}
🔥 Active (7 days): {len(active_users)}
🏆 Total XP: {total_xp}
✅ XP per Approval: {XP_PER_APPROVAL}
📈 Approvals Needed: {APPROVALS_NEEDED}

👑 Admin Commands:
/addxp, /resetlinks, /checkusers
"""
    
    await update.message.reply_text(debug_text)

async def resetlinks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin access required!")
        return
    
    # Implementation for resetting approval links
    await update.message.reply_text("🔄 Approval links reset feature coming soon!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    
    user = update.effective_user
    create_user(user.id, user.username, user.first_name, user.last_name)
    
    # Award small XP for active participation
    update_user_xp(user.id, 1, "comment")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("addxp", addxp))
    application.add_handler(CommandHandler("checkusers", checkusers))
    application.add_handler(CommandHandler("resetlinks", resetlinks))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    logger.info("🤖 EliteXPBot starting...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    # Start health server in background thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info("🩺 Health server started in background")
    
    # Start bot
    main()