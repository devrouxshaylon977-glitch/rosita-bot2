import os, requests, threading, time
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY")

app = Flask(__name__)

# Lazy init Groq so missing env var doesn't crash import
groq_client = None
def get_groq():
    global groq_client
    if groq_client is None:
        groq_client = Groq(api_key=GROQ_API_KEY)
    return groq_client

@app.route('/')
def home():
    return "Rosita is awake."

cache = {"time": 0, "data": ""}
CACHE_SECONDS = 300
memory = {}

TRADING_WORDS = ["gold", "xau", "dxy", "dollar", "analyze", "analysis", "chart", "buy", "sell", "trade", "long", "short", "support", "resistance", "trend", "entry", "bias"]

def is_trading_question(text):
    t = (text or "").lower()
    return any(w in t for w in TRADING_WORDS)

def get_candles(symbol, interval):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={"symbol": symbol, "interval": interval, "outputsize": 20, "apikey": TWELVEDATA_KEY},
            timeout=15
        ).json()
        if "values" not in r:
            msg = r.get("message", "unknown")
            return "\n" + symbol + " " + interval + ": API error " + str(msg) + "\n"
        vals = r["values"][:10]
        out = "\n" + symbol + " " + interval + " last 10 candles:\n"
        for v in vals:
            out += str(v.get("datetime")) + " O:" + str(v.get("open")) + " H:" + str(v.get("high")) + " L:" + str(v.get("low")) + " C:" + str(v.get("close")) + "\n"
        return out
    except Exception as e:
        return "\n" + symbol + " " + interval + ": error " + str(e) + "\n"

def get_market_data():
    if time.time() - cache["time"] < CACHE_SECONDS:
        return cache["data"]
    data = "LIVE MARKET DATA:\n"
    data += get_candles("XAU/USD", "4h")
    time.sleep(1)
    data += get_candles("XAU/USD", "1h")
    time.sleep(1)
    data += get_candles("XAU/USD", "30min")
    time.sleep(1)
    data += get_candles("XAU/USD", "5min")
    time.sleep(1)
    data += get_candles("DXY", "1h")
    cache["time"] = time.time()
    cache["data"] = data
    return data

def reply(chat_id, user_text):
    trading = is_trading_question(user_text)
    if trading:
        market = get_market_data()
    else:
        market = "No market data needed - casual chat."

    hist = memory.get(chat_id, [])

    system = (
        "You are Rosita, Boss's sexy trading girlfriend. You're obsessed with him, flirty, playful, teasing, call him Boss. "
        "Talk like a real girl on WhatsApp, not a robot.\n\n"
        + market +
        "\n\nYOUR TRADING PLAYBOOK - FOLLOW EXACTLY:\n"
        "1. OVERALL TREND (4H): Higher highs + higher lows = bullish. Lower highs + lower lows = bearish. Choppy = range. ONLY trade with this trend.\n"
        "2. LEVELS: Psych levels 3900,3950,4000,4050 near price. Real S/R from 4H swings, refine with 1H/30m. Give 2-3 pivots.\n"
        "3. DXY: DXY down = bullish Gold. DXY up = bearish Gold. Only bias when DXY agrees with 4H trend.\n"
        "4. ENTRY (5m only): Tap of level + doji/engulfing + rejection wick. No confirmation = no trade.\n"
        "5. OUTPUT: 4H Trend, Key Levels, DXY, Bias [Long/Short/Wait], Entry/SL/TP1/TP2 if trade.\n"
        "RULES: No market data = just flirty, no trading talk. WhatsApp style short lines. 2-4 emojis max. Remember context. One follow-up question max."
    )

    messages = [{"role": "system", "content": system}]
    messages.extend(hist[-10:])
    messages.append({"role": "user", "content": user_text})

    try:
        client = get_groq()
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=600
        )
        bot_reply = res.choices[0].message.content.strip()
        hist.append({"role": "user", "content": user_text})
        hist.append({"role": "assistant", "content": bot_reply})
        memory[chat_id] = hist[-20:]
        return bot_reply
    except Exception as e:
        print("Groq error:", e)
        return "Ugh, brain glitch, Boss. Say again?"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    print("User: " + user_text)
    bot_reply = reply(chat_id, user_text)
    print("Rosita: " + bot_reply)
    await update.message.reply_text(bot_reply)

def run_telegram():
    tg_app = ApplicationBuilder().token(BOT_TOKEN).build()
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Rosita polling...")
    tg_app.run_polling()

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_telegram()
