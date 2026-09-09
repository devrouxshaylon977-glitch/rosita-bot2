import os, threading, requests, traceback
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

GROQ_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

print(f"GROQ_KEY set: {bool(GROQ_KEY)}")
print(f"TELEGRAM_TOKEN set: {bool(TELEGRAM_TOKEN)}")

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Rosita is alive"

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_text = update.message.text
        print(f"Received: {user_text}")
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
        answer = r.json()["choices"][0]["message"]["content"]
        await update.message.reply_text(answer)
    except Exception as e:
        print(f"Reply error: {e}")
        traceback.print_exc()

def run_telegram():
    try:
        print("Starting Telegram polling...")
        if not TELEGRAM_TOKEN:
            print("ERROR: TELEGRAM_TOKEN is missing!")
            return
        app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
        print("Telegram started successfully")
        app_tg.run_polling()
    except Exception as e:
        print(f"Telegram failed to start: {e}")
        traceback.print_exc()

threading.Thread(target=run_telegram, daemon=True).start()

if __name__ == "__main__":
    app_flask.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
