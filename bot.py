import os
import logging
import sqlite3
import asyncio
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

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

# Health check server with multiple endpoints
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
        elif self.path == '/':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Telegram XP Bot is running!')
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
    logger.info("🩺 Health server running on port 8000 with ping endpoint")
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
            last_message_time TIMESTAMP,
            daily_bonus_claimed TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_bonus (
            user_id INTEGER PRIMARY KEY,
            last_claimed TIMESTAMP,
            streak_count INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized!")

init_db()

# XP system configuration
XP_PER_LEVEL = 100
LEVEL_MULTIPLIER = 1.5

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
            'last_message_time': user[6], 'daily_bonus_claimed': user[7],
            'created_at': user[8]
        }
    return None

def create_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users 
        (user_id, username, first_name, last_name, xp, level, last_message_time) 
        VALUES (?, ?, ?, ?, 0, 1, ?)
    ''', (user_id, username, first_name, last_name, datetime.now()))
    conn.commit()
    conn.close()

def update_user_xp(user_id, xp_to_add):
    user = get_user(user_id)
    if not user: return None
    
    new_xp = user['xp'] + xp_to_add
    new_level = calculate_level(new_xp)
    
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET xp = ?, level = ?, last_message_time = ? WHERE user_id = ?',
                  (new_xp, new_level, datetime.now(), user_id))
    conn.commit()
    conn.close()
    
    return {'old_level': user['level'], 'new_level': new_level, 'old_xp': user['xp'], 'new_xp': new_xp}

def calculate_level(xp):
    level = 1
    required_xp = XP_PER_LEVEL
    while xp >= required_xp:
        level += 1
        xp -= required_xp
        required_xp = int(required_xp * LEVEL_MULTIPLIER)
    return level

def xp_for_next_level(current_level, current_xp):
    xp_needed = XP_PER_LEVEL
    for i in range(1, current_level):
        xp_needed = int(xp_needed * LEVEL_MULTIPLIER)
    
    xp_in_current_level = current_xp
    temp_xp_needed = XP_PER_LEVEL
    for i in range(1, current_level):
        xp_in_current_level -= temp_xp_needed
        temp_xp_needed = int(temp_xp_needed * LEVEL_MULTIPLIER)
    
    return xp_needed - xp_in_current_level

def get_leaderboard(limit=10):
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, first_name, xp, level FROM users ORDER BY xp DESC LIMIT ?', (limit,))
    leaderboard = cursor.fetchall()
    conn.close()
    return leaderboard

def claim_daily_bonus(user_id):
    user = get_user(user_id)
    if not user: return None
    
    now = datetime.now()
    conn = sqlite3.connect('xp_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM daily_bonus WHERE user_id = ?', (user_id,))
    bonus_record = cursor.fetchone()
    
    if bonus_record:
        last_claimed = datetime.fromisoformat(bonus_record[1])
        streak_count = bonus_record[2]
        
        if last_claimed.date() == now.date():
            conn.close()
            return {'success': False, 'reason': 'already_claimed'}
        elif last_claimed.date() == (now.date() - timedelta(days=1)):
            streak_count += 1
        else:
            streak_count = 1
    else:
        streak_count = 1
        cursor.execute('INSERT INTO daily_bonus (user_id, last_claimed, streak_count) VALUES (?, ?, ?)',
                      (user_id, now, streak_count))
    
    bonus_xp = 50 + (streak_count * 10)
    cursor.execute('INSERT OR REPLACE INTO daily_bonus (user_id, last_claimed, streak_count) VALUES (?, ?, ?)',
                  (user_id, now, streak_count))
    
    update_result = update_user_xp(user_id, bonus_xp)
    conn.commit()
    conn.close()
    
    return {'success': True, 'bonus_xp': bonus_xp, 'streak_count': streak_count, 'level_update': update_result}

# Bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = f"""
👋 Welcome {user.first_name} to XP Bot! 🎮

I'll track your activity and reward you with XP and levels!

📊 **Available Commands:**
/start - Start the bot
/profile - Check your profile
/leaderboard - See top users
/daily - Claim daily bonus
/help - Show this help message

Earn XP by sending messages in the chat! 🚀
    """
    
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 **XP Bot Help** 📚

**Commands:**
/start - Start using the bot
/profile - View your profile and stats
/leaderboard - See the top 10 users
/daily - Claim your daily XP bonus
/help - Show this help message

**How it works:**
• Earn 1-5 XP for each message you send
• Level up by earning more XP
• Claim daily bonuses for extra XP
• Compete with friends on the leaderboard!

Happy leveling! 🎉
    """
    
    await update.message.reply_text(help_text)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_user(user.id)
    
    if not user_data:
        create_user(user.id, user.username, user.first_name, user.last_name)
        user_data = get_user(user.id)
    
    xp_needed = xp_for_next_level(user_data['level'], user_data['xp'])
    
    profile_text = f"""
📊 **Profile for {user.first_name}**

🏆 Level: {user_data['level']}
⭐ XP: {user_data['xp']}
🎯 XP to next level: {xp_needed}

🕒 Member since: {user_data['created_at'][:10]}
    """
    
    await update.message.reply_text(profile_text)

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = get_leaderboard(10)
    
    if not top_users:
        await update.message.reply_text("📊 No users on leaderboard yet!")
        return
    
    leaderboard_text = "🏆 **Top 10 Users** 🏆\n\n"
    
    for i, (user_id, username, first_name, xp, level) in enumerate(top_users, 1):
        display_name = first_name or username or f"User {user_id}"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        leaderboard_text += f"{medal} {display_name} - Level {level} ({xp} XP)\n"
    
    await update.message.reply_text(leaderboard_text)

async def daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_user(user.id)
    
    if not user_data:
        create_user(user.id, user.username, user.first_name, user.last_name)
        user_data = get_user(user.id)
    
    result = claim_daily_bonus(user.id)
    
    if result['success']:
        bonus_text = f"""
🎁 **Daily Bonus Claimed!** 🎁

+{result['bonus_xp']} XP added to your account!
🔥 Streak: {result['streak_count']} days in a row!

You're now at Level {result['level_update']['new_level']} with {result['level_update']['new_xp']} XP!

Come back tomorrow for more bonus XP! ⏰
        """
    else:
        bonus_text = "❌ You've already claimed your daily bonus today! Come back tomorrow."
    
    await update.message.reply_text(bonus_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all messages and award XP"""
    if not update.message or not update.message.text:
        return
    
    user = update.effective_user
    message_text = update.message.text
    
    # Ignore command messages for XP
    if message_text.startswith('/'):
        return
    
    user_data = get_user(user.id)
    if not user_data:
        create_user(user.id, user.username, user.first_name, user.last_name)
        user_data = get_user(user.id)
    
    # Check cooldown (prevent spam)
    last_message_time = user_data.get('last_message_time')
    if last_message_time:
        last_time = datetime.fromisoformat(last_message_time) if isinstance(last_message_time, str) else last_message_time
        if datetime.now() - last_time < timedelta(seconds=30):
            return
    
    # Award random XP between 1-5
    import random
    xp_to_add = random.randint(1, 5)
    
    update_result = update_user_xp(user.id, xp_to_add)
    
    # Check if user leveled up
    if update_result and update_result['old_level'] < update_result['new_level']:
        level_up_text = f"""
🎉 **LEVEL UP!** 🎉

{user.first_name} reached Level {update_result['new_level']}! 🏆

Keep going! You're doing great! 🚀
        """
        await update.message.reply_text(level_up_text)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors in the bot"""
    logger.error(f"Exception while handling an update: {context.error}")

def main():
    """Main function to run the bot"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("daily", daily_bonus))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    logger.info("🤖 Bot starting...")
    
    # Use run_polling instead of asyncio.run to avoid event loop issues
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    # Start health server in background thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info("🩺 Health server started in background")
    
    # Start bot
    main()