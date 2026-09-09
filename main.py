import os, threading, requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

GROQ_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "Rosita is alive"

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_KEY}"},
        json={"model": "llama-3.1-8b-instant",
              "messages": [{"role": "system", "content": "You are Rosita, friendly AI assistant."},
                           {"role": "user", "content": user_text}]})
    await update.message.reply_text(r.json()["choices"][0]["message"]["content"]})

def run_telegram():
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    app_tg.run_polling()

threading.Thread(target=run_telegram, daemon=True).start()

if __name__ == "__main__":
    app_flask.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
