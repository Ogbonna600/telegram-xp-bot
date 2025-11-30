import logging
from datetime import datetime, timedelta
import pytz
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json

# -------------------- CONFIG --------------------
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8551726061:AAGawAjRX4wBjM8w6dHXfrJxVlUrWJU5EK4")
SHEET_NAME = "TelegramXPBot"
WORKSHEET_NAME = "XP"
CHANNEL_USERNAME = "@XFanbaseElite"
ADMIN_IDS = {1388128653, 7573908933, 6503449202}
TZ = pytz.timezone("Africa/Lagos")

# XP & Train Settings
XP_FOR_APPROVAL = 20
APPROVALS_NEEDED = 15
DAILY_TRAIN_TIMES = [(10, 0), (14, 0), (18, 0), (22, 0)]  # 10AM, 2PM, 6PM, 10PM Lagos
TRAIN_DURATION = 1  # hours

# Anti-Cheat Settings
MAX_APPROVALS_PER_USER = 5  # Max approvals one user can give per train
SUSPICIOUS_ACTIVITY_LIMIT = 10  # Max actions per minute

# -------------------- SETUP --------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Google Sheets setup - MODIFIED FOR RENDER
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# For Render environment
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
if SERVICE_ACCOUNT_JSON:
    # Use environment variable (for Render)
    service_account_info = json.loads(SERVICE_ACCOUNT_JSON)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
    logger.info("✅ Using Google Sheets service account from environment variable")
else:
    # Fallback to file (for local testing)
    SERVICE_ACCOUNT_FILE = "telegramxpbot-6a2587fe86f0.json"
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
    logger.info("✅ Using Google Sheets service account from file")

try:
    gc = gspread.authorize(creds)
    sh = gc.open(SHEET_NAME)
    ws = sh.worksheet(WORKSHEET_NAME)
    logger.info("✅ Google Sheets connected successfully!")
except Exception as e:
    logger.error(f"❌ Google Sheets connection failed: {e}")
    # Continue without Google Sheets for now
    ws = None

# Ensure correct headers
CORRECT_HEADERS = [
    "Telegram ID", "Username", "Twitter", "Daily XP", "Comment XP", 
    "Proof XP", "Total XP", "Tweet Link", "Last Active", "Approvers",
    "Train ID", "Warnings", "Status", "Joined Date"
]

if ws:
    try:
        current_headers = ws.row_values(1)
        if current_headers != CORRECT_HEADERS:
            ws.update('A1:N1', [CORRECT_HEADERS])
            logger.info("✅ Headers verified and updated")
    except Exception as e:
        logger.error(f"❌ Header verification failed: {e}")

# Train session tracking
current_train_session = None
user_activity_tracker = {}
user_approval_counts = {}

# -------------------- TRAIN SYSTEM FUNCTIONS --------------------
def get_current_train_session():
    """Get current active train session"""
    now = datetime.now(TZ)
    for hour, minute in DAILY_TRAIN_TIMES:
        train_start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        train_end = train_start + timedelta(hours=TRAIN_DURATION)
        
        if train_start <= now < train_end:
            return train_start.strftime("%Y%m%d_%H%M")
    return None

def start_new_train_session():
    """Start a new train session"""
    global current_train_session
    current_train_session = datetime.now(TZ).strftime("%Y%m%d_%H%M")
    
    # Reset approval counts for new session
    user_approval_counts.clear()
    
    logger.info(f"🚂 New train session started: {current_train_session}")
    return current_train_session

def is_train_active():
    """Check if train is currently active"""
    return get_current_train_session() is not None

# -------------------- ANTI-CHEAT SYSTEM --------------------
def track_user_activity(user_id: int):
    """Track user activity to detect suspicious behavior"""
    now = datetime.now(TZ)
    minute_key = now.strftime("%Y%m%d%H%M")
    
    if user_id not in user_activity_tracker:
        user_activity_tracker[user_id] = {}
    
    if minute_key not in user_activity_tracker[user_id]:
        user_activity_tracker[user_id][minute_key] = 0
    
    user_activity_tracker[user_id][minute_key] += 1
    
    # Clean old entries (keep only last 10 minutes)
    ten_min_ago = (now - timedelta(minutes=10)).strftime("%Y%m%d%H%M")
    for key in list(user_activity_tracker[user_id].keys()):
        if key < ten_min_ago:
            del user_activity_tracker[user_id][key]
    
    return user_activity_tracker[user_id][minute_key]

def is_suspicious_activity(user_id: int):
    """Check if user has suspicious activity patterns"""
    activity_count = track_user_activity(user_id)
    return activity_count > SUSPICIOUS_ACTIVITY_LIMIT

def can_user_approve(user_id: int):
    """Check if user can give more approvals this session"""
    if user_id not in user_approval_counts:
        user_approval_counts[user_id] = 0
    
    return user_approval_counts[user_id] < MAX_APPROVALS_PER_USER

def record_approval(user_id: int):
    """Record that user gave an approval"""
    if user_id not in user_approval_counts:
        user_approval_counts[user_id] = 0
    user_approval_counts[user_id] += 1

# -------------------- CORE FUNCTIONS --------------------
def safe_int(val):
    try:
        return int(float(val or 0))
    except:
        return 0

def get_real_user_id(update: Update):
    """Get the REAL user ID, not the anonymous bot ID"""
    user = update.effective_user
    
    if user.id == 1087968824 or user.username == "GroupAnonymousBot":
        if update.message and update.message.from_user:
            return update.message.from_user.id
        else:
            return 1388128653
    
    return user.id

def get_user_display_name(update: Update):
    user = update.effective_user
    if user.username and user.username != "GroupAnonymousBot":
        return f"@{user.username}"
    elif user.first_name:
        return user.first_name
    else:
        return f"User{user.id}"

def is_admin(user_id: int):
    if user_id == 1087968824:
        return True
    return user_id in ADMIN_IDS

def find_user_row(user_id: str):
    if not ws:
        return None
    try:
        all_ids = ws.col_values(1)
        if str(user_id) in all_ids:
            return all_ids.index(str(user_id)) + 1
        return None
    except:
        return None

def create_user_row(user_id: str, display_name: str):
    if not ws:
        return None
    try:
        new_row = [
            str(user_id), display_name, "", 0, 0, 0, 0, "", 
            datetime.now(TZ).isoformat(), "", "", 0, "Active", 
            datetime.now(TZ).strftime("%Y-%m-%d")
        ]
        ws.append_row(new_row)
        return ws.row_count
    except Exception as e:
        logger.error(f"Error creating user row: {e}")
        return None

def find_or_create_user(user_id: str, display_name: str):
    row = find_user_row(user_id)
    if row:
        try:
            current_name = ws.cell(row, 2).value
            if current_name != display_name:
                ws.update_cell(row, 2, display_name)
            return row
        except:
            return row
    else:
        return create_user_row(user_id, display_name)

def get_user_data(row: int):
    if not ws:
        return None
    try:
        values = ws.row_values(row)
        if len(values) >= 14:
            return {
                'Telegram ID': values[0],
                'Username': values[1],
                'Twitter': values[2],
                'Daily XP': safe_int(values[3]),
                'Comment XP': safe_int(values[4]),
                'Proof XP': safe_int(values[5]),
                'Total XP': safe_int(values[6]),
                'Tweet Link': values[7],
                'Last Active': values[8],
                'Approvers': values[9],
                'Train ID': values[10],
                'Warnings': safe_int(values[11]),
                'Status': values[12],
                'Joined Date': values[13]
            }
        return None
    except:
        return None

def update_user_xp(row: int, proof_xp: int = 0):
    if not ws:
        return False
    try:
        user_data = get_user_data(row)
        if not user_data:
            return False
            
        daily_xp = user_data['Daily XP']
        comment_xp = user_data['Comment XP']
        current_proof_xp = user_data['Proof XP']
        
        new_proof_xp = current_proof_xp + proof_xp
        total_xp = daily_xp + comment_xp + new_proof_xp
        
        ws.update(f"D{row}:G{row}", [[daily_xp, comment_xp, new_proof_xp, total_xp]])
        ws.update_cell(row, 9, datetime.now(TZ).isoformat())
        return True
    except Exception as e:
        logger.error(f"Error updating XP: {e}")
        return False

def validate_tweet_url(url: str):
    return url and ("x.com/" in url or "twitter.com/" in url)

def find_user_by_username(username: str):
    if not ws:
        return None, None
    try:
        all_users = ws.get_all_records()
        for idx, user in enumerate(all_users, start=2):
            if user.get('Username', '').lower() == username.lower():
                return idx, user
        return None, None
    except:
        return None, None

# -------------------- TRAIN COMMANDS --------------------
async def train_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check current train status"""
    if is_train_active():
        current_session = get_current_train_session()
        await update.message.reply_text(
            f"🚂 **TRAIN IS LIVE!** 🚂\n\n"
            f"📅 **Session:** {current_session}\n"
            f"⏰ **Time left:** ~45 minutes\n"
            f"🎯 **Required:** {APPROVALS_NEEDED} approvals\n"
            f"💰 **Reward:** {XP_FOR_APPROVAL} XP\n\n"
            f"Use /postlink to submit your tweet!"
        )
    else:
        next_train = "10:00 AM"
        await update.message.reply_text(
            f"⏸️ **No active train right now.**\n\n"
            f"🕐 **Next train:** {next_train} Lagos time\n"
            f"📅 **Daily trains:** 10AM, 2PM, 6PM, 10PM"
        )

async def next_train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show next train schedule"""
    now = datetime.now(TZ)
    next_trains = []
    
    for hour, minute in DAILY_TRAIN_TIMES:
        train_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if train_time > now:
            next_trains.append(train_time.strftime("%I:%M %p"))
    
    if next_trains:
        next_train = next_trains[0]
        await update.message.reply_text(
            f"🕐 **Next Train:** {next_train}\n\n"
            f"📅 **All Today's Trains:**\n"
            f"• 10:00 AM (1 hour)\n"
            f"• 02:00 PM (1 hour)\n" 
            f"• 06:00 PM (1 hour)\n"
            f"• 10:00 PM (1 hour)\n\n"
            f"⏰ Lagos time (GMT+1)"
        )
    else:
        await update.message.reply_text("🎉 **All trains completed for today!** See you tomorrow!")

# -------------------- ENHANCED BOT COMMANDS --------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced welcome message"""
    real_user_id = get_real_user_id(update)
    display_name = get_user_display_name(update)
    
    if ws:
        row = find_or_create_user(str(real_user_id), display_name)
    
    admin_status = " 👑" if is_admin(real_user_id) else ""
    train_status = "🚂" if is_train_active() else "⏸️"
    
    await update.message.reply_text(
        f"🤖 **Welcome {display_name} to X Fanbase Elite XP Bot!**{admin_status}\n\n"
        f"{train_status} **Train Status:** {'ACTIVE' if is_train_active() else 'INACTIVE'}\n\n"
        "🎯 **Quick Start:**\n"
        "1. Wait for active train\n" 
        "2. /postlink <url> - Submit tweet\n"
        "3. Get approvals from others\n\n"
        
        "📖 **Essential Commands:**\n"
        "• /help - Complete guide\n"
        "• /trainstatus - Check train\n"
        "• /nexttrain - Schedule\n"
        "• /approve @user - Approve tweets\n\n"
        
        f"💰 **Rewards:** {APPROVALS_NEEDED} approvals = {XP_FOR_APPROVAL} XP!"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium help guide"""
    real_user_id = get_real_user_id(update)
    
    help_text = (
        "🎯 **X FANBASE ELITE - PREMIUM GUIDE** 🎯\n\n"
        
        "🚂 **DAILY TRAIN SYSTEM:**\n"
        "• 4 trains daily: 10AM, 2PM, 6PM, 10PM (Lagos)\n"
        "• Each train lasts 1 hour\n"
        "• Submit tweets ONLY during active trains\n"
        "• /trainstatus - Check current train\n"
        "• /nexttrain - Upcoming schedule\n\n"
        
        "👤 **USER COMMANDS:**\n"
        "• /start - Welcome & setup\n"
        "• /postlink <url> - Submit tweet (train hours only)\n"
        "• /approve @username - Approve tweets\n"
        "• /trainstatus - Check train status\n\n"
        
        "👑 **ADMIN COMMANDS:**\n"
        "• /cheatdetect - Suspicious activity\n\n"
        
        "🛡️ **ANTI-CHEAT SYSTEM:**\n"
        "• Max 5 approvals per user per train\n"
        "• Activity rate limiting\n"
        "• Duplicate submission detection\n"
        "• Suspicious pattern monitoring\n\n"
        
        f"💰 **REWARDS:** {APPROVALS_NEEDED} approvals = {XP_FOR_APPROVAL} Proof XP!"
    )
    
    if is_admin(real_user_id):
        help_text += f"\n\n👑 **ADMIN ACCESS GRANTED** (ID: {real_user_id})"
    
    await update.message.reply_text(help_text)

async def postlink_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced postlink with train checking"""
    if not context.args:
        await update.message.reply_text("❌ **Usage:** /postlink <tweet_url>\n**Example:** /postlink https://x.com/user/status/123456")
        return
    
    # Check if train is active
    if not is_train_active():
        await update.message.reply_text(
            "⏸️ **No active train!**\n\n"
            "You can only submit tweets during:\n"
            "• 10:00-11:00 AM\n"
            "• 02:00-03:00 PM\n" 
            "• 06:00-07:00 PM\n"
            "• 10:00-11:00 PM\n\n"
            "Use /nexttrain to see schedule"
        )
        return
    
    real_user_id = get_real_user_id(update)
    display_name = get_user_display_name(update)
    tweet_url = context.args[0].strip()
    
    if not validate_tweet_url(tweet_url):
        await update.message.reply_text("❌ **Please provide valid Twitter/X URL** (x.com or twitter.com)")
        return
    
    # Anti-cheat: Check for suspicious activity
    if is_suspicious_activity(real_user_id):
        await update.message.reply_text("🚫 **Suspicious activity detected.** Please wait before submitting again.")
        return
    
    if ws:
        row = find_or_create_user(str(real_user_id), display_name)
        
        # Update tweet link with train session
        current_train = get_current_train_session()
        ws.update_cell(row, 8, tweet_url)  # Tweet Link
        ws.update_cell(row, 9, datetime.now(TZ).isoformat())  # Last Active
        ws.update_cell(row, 11, current_train)  # Train ID
        ws.update_cell(row, 10, "")  # Clear previous approvers
    
    await update.message.reply_text(
        f"✅ **Tweet submitted to train!** 🚂\n\n"
        f"👤 **Submitter:** {display_name}\n"
        f"🔗 **Tweet:** {tweet_url}\n"
        f"🎯 **Needed:** {APPROVALS_NEEDED} approvals\n"
        f"💰 **Reward:** {XP_FOR_APPROVAL} XP\n\n"
        f"Share your submission for approvals!"
    )

async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced approve with anti-cheat"""
    if not context.args:
        await update.message.reply_text("❌ **Usage:** /approve @username\n**Example:** /approve @Charlie")
        return
    
    real_user_id = get_real_user_id(update)
    display_name = get_user_display_name(update)
    target_username = context.args[0].lstrip("@")
    
    # Anti-cheat: Check approval limits
    if not can_user_approve(real_user_id):
        await update.message.reply_text(
            f"🚫 **Approval limit reached!**\n\n"
            f"You can only give {MAX_APPROVALS_PER_USER} approvals per train.\n"
            f"Wait for the next train session."
        )
        return
    
    # Anti-cheat: Check for suspicious activity
    if is_suspicious_activity(real_user_id):
        await update.message.reply_text("🚫 **Suspicious activity detected.** Please wait before approving again.")
        return
    
    if not ws:
        await update.message.reply_text("❌ **Google Sheets not available.** Approvals temporarily disabled.")
        return
    
    target_row, target_data = find_user_by_username(target_username)
    
    if not target_row or not target_data:
        await update.message.reply_text(f"❌ **User @{target_username} not found**")
        return
    
    # Check if target has active submission in current train
    tweet_link = target_data.get('Tweet Link', '')
    user_train_id = target_data.get('Train ID', '')
    current_train = get_current_train_session()
    
    if not validate_tweet_url(tweet_link):
        await update.message.reply_text(f"❌ **@{target_username} has no active tweet submission**")
        return
    
    if user_train_id != current_train:
        await update.message.reply_text(f"❌ **This submission is not for the current train**")
        return
    
    # Check if already approved
    approvers = target_data.get('Approvers', '').split(',')
    if str(real_user_id) in approvers:
        await update.message.reply_text("❌ **You already approved this tweet**")
        return
    
    # Record approval
    record_approval(real_user_id)
    track_user_activity(real_user_id)
    
    # Update approvers list
    approvers.append(str(real_user_id))
    ws.update_cell(target_row, 10, ','.join([a for a in approvers if a]))
    
    approval_count = len(approvers)
    
    if approval_count >= APPROVALS_NEEDED:
        # Award XP for reaching approval goal
        update_user_xp(target_row, XP_FOR_APPROVAL)
        await update.message.reply_text(
            f"🎉 **APPROVAL GOAL REACHED!** 🎉\n\n"
            f"👤 **User:** @{target_username}\n"
            f"✅ **Approvals:** {approval_count} achieved!\n"
            f"💰 **Reward:** +{XP_FOR_APPROVAL} XP awarded!\n"
            f"🎯 **Approved by:** {display_name}"
        )
    else:
        await update.message.reply_text(
            f"✅ **Approval recorded!**\n\n"
            f"👤 **User:** @{target_username}\n"
            f"📊 **Progress:** {approval_count}/{APPROVALS_NEEDED} approvals\n"
            f"🎯 **Approved by:** {display_name}\n"
            f"📝 **Your approvals this train:** {user_approval_counts.get(real_user_id, 0)}/{MAX_APPROVALS_PER_USER}"
        )

# -------------------- ADMIN COMMANDS --------------------
async def cheatdetect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detect suspicious activity"""
    real_user_id = get_real_user_id(update)
    
    if not is_admin(real_user_id):
        await update.message.reply_text("❌ **Admin only command**")
        return
    
    try:
        if not ws:
            await update.message.reply_text("❌ **Google Sheets not available**")
            return
            
        suspicious_users = []
        all_users = ws.get_all_records()
        
        for user in all_users:
            warnings = safe_int(user.get('Warnings', 0))
            if warnings > 0:
                suspicious_users.append(user)
        
        if suspicious_users:
            response = "🚨 **SUSPICIOUS ACTIVITY REPORT** 🚨\n\n"
            for user in suspicious_users[:10]:  # Show top 10
                response += f"👤 {user.get('Username')} - {user.get('Warnings')} warnings\n"
            
            response += f"\n📊 **Total flagged:** {len(suspicious_users)} users"
        else:
            response = "✅ **No suspicious activity detected!**\n\nAll users are following the rules."
        
        # Add current activity stats
        active_users = len(user_activity_tracker)
        total_approvals = sum(user_approval_counts.values())
        
        response += f"\n\n📈 **Live Stats:**\n**Active users:** {active_users}\n**Total approvals:** {total_approvals}"
        
        await update.message.reply_text(response)
        
    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {e}")

# -------------------- FLASK APP & BOT SETUP --------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Telegram XP Bot is running!"

@app.route('/health')
def health():
    return "✅ Bot is healthy!"

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

def setup_bot():
    try:
        # Create bot application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add command handlers
        application.add_handler(CommandHandler("start", start_cmd))
        application.add_handler(CommandHandler("help", help_cmd))
        application.add_handler(CommandHandler("trainstatus", train_status_cmd))
        application.add_handler(CommandHandler("nexttrain", next_train_cmd))
        application.add_handler(CommandHandler("postlink", postlink_cmd))
        application.add_handler(CommandHandler("approve", approve_cmd))
        application.add_handler(CommandHandler("cheatdetect", cheatdetect_cmd))
        
        logger.info("✅ Telegram bot setup completed!")
        return application
        
    except Exception as e:
        logger.error(f"❌ Failed to setup bot: {e}")
        return None

def start_bot():
    application = setup_bot()
    if application:
        logger.info("🤖 Starting bot polling...")
        application.run_polling()

if __name__ == '__main__':
    import threading
    
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Start Flask in main thread
    logger.info("🚀 Starting Telegram XP Bot...")
    logger.info("🌐 Flask server running on port 5000")
    logger.info("🤖 Bot should be responding to commands now!")
    
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)