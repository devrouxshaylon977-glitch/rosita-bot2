import os, threading, requests, asyncio
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

GROQ_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Rosita is alive"

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": "You are Rosita, friendly AI assistant."},
                    {"role": "user", "content": user_text}
                ]
            },
            timeout=30
        )
        data = r.json()
        answer = data["choices"][0]["message"]["content"]
    except Exception as e:
        answer = f"Sorry, I had an error: {e}"
    await update.message.reply_text(answer)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def run_telegram():
    if not TELEGRAM_TOKEN:
        print("Missing TELEGRAM_TOKEN")
        return
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    print("Telegram polling started")
    app_tg.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    # Flask in background, Telegram in main thread (required)
    threading.Thread(target=run_flask, daemon=True).start()
    run_telegram()
