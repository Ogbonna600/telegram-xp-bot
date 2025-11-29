import os
import logging
from flask import Flask

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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

if __name__ == '__main__':
    try:
        # Check if bot token is set
        BOT_TOKEN = os.environ.get('BOT_TOKEN')
        if BOT_TOKEN:
            logger.info("✅ BOT_TOKEN environment variable is set!")
        else:
            logger.warning("⚠️ BOT_TOKEN environment variable is missing")
        
        # Start Flask
        logger.info("🚀 Starting Telegram XP Bot...")
        logger.info("🌐 Flask server running on port 5000")
        
        # Run Flask app
        app.run(host='0.0.0.0', port=5000, debug=False)
        
    except Exception as e:
        logger.error(f"❌ Failed to start: {e}")
