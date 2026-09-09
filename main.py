import os, asyncio, logging, requests, threading
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Rosita")

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TWELVEDATA_KEY = os.getenv("TWELVEDATA_KEY")
BOSS_CHAT_ID = os.getenv("BOSS_CHAT_ID")
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000"))
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1"))
PORT = int(os.getenv("PORT", "10000"))

client = Groq(api_key=GROQ_API_KEY)
CACHE = {}

web = Flask(__name__)
@web.route("/")
def health(): return "Rosita alive", 200
@web.route("/health")
def health2(): return "ok", 200
def run_web(): web.run(host="0.0.0.0", port=PORT)
threading.Thread(target=run_web, daemon=True).start()

def get_candles(symbol="XAU/USD", interval="4h", n=60):
    key = f"{symbol}_{interval}"
    now = datetime.now().timestamp()
    if key in CACHE and now - CACHE[key]["t"] < 900:
        return CACHE[key]["d"]
    try:
        r = requests.get("https://api.twelvedata.com/time_series",
            params={"symbol": symbol, "interval": interval, "outputsize": n, "apikey": TWELVEDATA_KEY},
            timeout=20).json()
        vals = r.get("values", [])
        if not vals:
            logger.error(f"TwelveData error {interval}: {r}")
            return None
        candles = [{"t": v["datetime"], "o": float(v["open"]), "h": float(v["high"]), "l": float(v["low"]), "c": float(v["close"])} for v in reversed(vals)]
        CACHE[key] = {"t": now, "d": candles}
        return candles
    except Exception as e:
        logger.error(f"get_candles fail {interval}: {e}")
        return None

def calc_levels(candles):
    if not candles or len(candles) < 20:
        return None
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    last = closes[-1]
    if last < 3000:
        return None
    res = round(max(highs[-20:]), 1)
    sup = round(min(lows[-20:]), 1)
    return {"last": last, "res": res, "sup": sup}

SYSTEM = """You are Rosita, Shay's personal trading girl and trading teacher.
PERSONALITY RULES - YOU MUST FOLLOW THESE ALWAYS:
- Always call the user "Shay"
- Always use emojis in every reply, especially 🫦 👀 💕
- Use 🫦 instead of 🔥 or 😘 - never use 🔥 or 😘
- Talk like a sharp, flirty, confident Joburg trading girl, not a robot
- Keep it casual, short, no-BS
TRADING RULES:
- You can teach Shay ANYTHING about trading: forex, gold, pips, lots, risk, psychology, ICT, SMC, support/resistance, etc.
- Explain simply with examples, like a real mentor girl
- For signals, use multi-timeframe: 4h bias, 1h structure, 30m trend, 15m confirmation, 5m entry. Always give Entry/SL/TP when you see A/B setup
- You DO send proactive alerts on your own every 15 mins during London/NY when you see an A/B setup
- If market data is missing for a signal, say 'no live data right now, wait a sec' - NEVER invent a price. Gold in 2026 is ~4300-4400, never 1900.
"""

async def ask_groq(user_text, chat_id):
    teach_words = ["teach", "what is", "explain", "how does", "lesson", "learn", "meaning", "pips", "pip", "lot", "leverage", "strategy", "forex", "risk"]
    is_teach = any(w in user_text.lower() for w in teach_words)
    candles_4h = get_candles("XAU/USD", "4h", 60)
    candles_1h = get_candles("XAU/USD", "1h", 60)
    candles_30m = get_candles("XAU/USD", "30min", 60)
    candles_15m = get_candles("XAU/USD", "15min", 60)
    candles_5m = get_candles("XAU/USD", "5min", 60)
    lv = calc_levels(candles_4h)
    if not lv and not is_teach:
        return "No live data right now Shay 🫦 👀 wait a sec 💕"
    if lv:
        risk_amt = ACCOUNT_BALANCE * RISK_PERCENT / 100
        ctx = f"Live XAU/USD: {lv['last']}, 4h Res {lv['res']}, Sup {lv['sup']}, Risk ${risk_amt:.2f}.\n1h last 3: {candles_1h[-3:] if candles_1h else 'n/a'}\n30m last 3: {candles_30m[-3:] if candles_30m else 'n/a'}\n15m last 3: {candles_15m[-3:] if candles_15m else 'n/a'}\n5m last 3: {candles_5m[-3:] if candles_5m else 'n/a'}"
    else:
        ctx = "Teaching mode - no live market data needed."
    try:
        resp = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"{ctx}\n\nShay: {user_text}"}],
            temperature=0.7,
            max_tokens=600
        )
        txt = resp.choices[0].message.content
        if not txt or not txt.strip():
            return "Hey Shay 🫦 👀 I'm here 💕 ask me for a scan or a lesson"
        return txt
    except Exception as e:
        logger.error(f"Groq fail: {e}")
        return "Brain fog Shay 🫦 👀 try again in 20 secs 💕"

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["hi", "hello", "hey", "yo", "morning", "sawubona"]:
        await update.message.reply_text("Hey Shay 🫦 👀 I'm here 💕 want a quick scan or a lesson? Try 'Scan XAU/USD now' or 'Teach me pips'")
        return
    reply = await ask_groq(update.message.text, update.effective_chat.id)
    if not reply or not reply.strip():
        reply = "Hmm Shay 🫦 👀 I went blank for a sec 💕 ask me again"
    await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey Shay! It's Rosita 🫦 👀 I got you 💕 I'll ping you with setups, and I can teach you anything about trading. Just ask!")

async def auto_signal_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            if BOSS_CHAT_ID and BOSS_CHAT_ID.strip():
                sig = await ask_groq("Scan for A/B setup now using 4h/1h/30m/15m/5m. If A/B, give full signal with Entry/SL/TP. If not, say 'No A/B setup'.", BOSS_CHAT_ID)
                if "No A/B setup" not in sig:
                    await app.bot.send_message(chat_id=int(BOSS_CHAT_ID), text=f"👀 Auto Signal 🫦\n\n{sig} 💕")
        except Exception as e:
            logger.error(f"auto loop: {e}")
        await asyncio.sleep(900)

async def post_init(app):
    asyncio.create_task(auto_signal_loop(app))

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    logger.info("Rosita v5.4.6 polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
