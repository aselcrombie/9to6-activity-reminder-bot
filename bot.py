import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Set Reminder", callback_data='set_reminder')],
        [InlineKeyboardButton("Cancel", callback_data='cancel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Welcome! Please choose an option:', reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == 'set_reminder':
        await context.application.job_queue.run_once(callback, when=60, context=query.message.chat_id)
        await query.edit_message_text(text='Reminder set!')
    elif query.data == 'cancel':
        await query.edit_message_text(text='Reminder cancelled.')

async def callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    await context.bot.send_message(job.chat_id, text='This is your reminder!')

async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.application.job_queue.run_once(callback, when=60, context=update.effective_chat.id)
    await update.message.reply_text('Reset reminder set!')

def main() -> None:
    application = ApplicationBuilder().token('YOUR_TOKEN_HERE').build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CommandHandler('reset', reset_handler))

    application.run_polling()

if __name__ == '__main__':
    main()