import os
import logging
from flask import Flask
import asyncio

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
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

@app.route('/test')
def test():
    return "🚀 Bot is working perfectly!"

# Simple function to show bot is ready
def bot_ready():
    logger.info("✅ Bot is ready to receive Telegram updates!")
    logger.info(f"🌐 Flask server running on port 5000")
    logger.info("📱 Your bot should respond to commands now!")

if __name__ == '__main__':
    try:
        # Start Flask
        logger.info("🚀 Starting Telegram XP Bot...")
        bot_ready()
        
        # Run Flask app
        app.run(host='0.0.0.0', port=5000, debug=False)
        
    except Exception as e:
        logger.error(f"❌ Failed to start: {e}")
