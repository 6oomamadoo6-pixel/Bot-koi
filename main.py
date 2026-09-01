from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

BOT_TOKEN = "8965685820:AAGuwWH9XkeIkrydQoJPnrkaUOFK5G9_V58"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات روشن شد و وصل است ✅")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("ربات در حال اجرا...")
    app.run_polling()

if __name__ == "__main__":
    main()
