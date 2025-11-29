import os
import logging
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get bot token from environment
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN environment variable is missing!")
    exit(1)

# Create Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Telegram XP Bot is running!"

@app.route('/health')
def health():
    return "✅ Bot is healthy!"

# Simple bot commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Welcome to X Fanbase Elite XP Bot!\n\n"
        "🚂 Train System:\n"
        "• 4 daily trains: 10AM, 2PM, 6PM, 10PM Lagos\n"
        "• Submit tweets during train hours\n\n"
        "📋 Commands:\n"
        "• /start - This message\n"
        "• /trainstatus - Check train status\n"
        "• /help - Full guide"
    )

async def trainstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚂 Train Status: INACTIVE\n\nNext train: 10:00 AM Lagos time")

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 **X FANBASE ELITE BOT** 🎯\n\n"
        "🚂 **Train Commands:**\n"
        "• /trainstatus - Check train status\n"
        "• /postlink <url> - Submit tweet\n\n"
        "👤 **User Commands:**\n"
        "• /start - Welcome message\n"
        "• /help - This guide\n\n"
        "💰 **Rewards:** 15 approvals = 20 XP!"
    )

def run_bot():
    try:
        # Create bot application
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("trainstatus", trainstatus))
        application.add_handler(CommandHandler("help", help))
        
        logger.info("🤖 Starting bot...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Bot failed to start: {e}")

def run_flask():
    try:
        logger.info("🌐 Starting Flask server...")
        app.run(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        logger.error(f"❌ Flask failed to start: {e}")

if __name__ == '__main__':
    import threading
    
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start bot in main thread
    run_bot()
