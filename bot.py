import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_text(
        f'Hi {user.first_name}! I am your Telegram bot. Send me any message and I will echo it back!'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = """
Available commands:
/start - Start the bot
/help - Show this help message
/about - Learn about this bot

You can also send me any text message and I will echo it back to you!
    """
    await update.message.reply_text(help_text)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send information about the bot."""
    await update.message.reply_text(
        'I am a simple Telegram bot built with Python and python-telegram-bot library. '
        'I can echo your messages and respond to commands!'
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Echo the user message."""
    await update.message.reply_text(f'You said: {update.message.text}')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors caused by updates."""
    logger.error(f'Update {update} caused error {context.error}')

def main():
    """Start the bot."""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token:
        logger.error('TELEGRAM_BOT_TOKEN environment variable is not set!')
        print('ERROR: Please set the TELEGRAM_BOT_TOKEN environment variable.')
        print('You can get your bot token from @BotFather on Telegram.')
        return
    
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    application.add_error_handler(error_handler)

    logger.info('Bot is starting...')
    print('Bot is running! Press Ctrl+C to stop.')
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
