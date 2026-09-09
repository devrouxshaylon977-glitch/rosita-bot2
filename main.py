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
            params={"symbol":symbol,"interval":interval,"outputsize":n,"apikey":TWELVEDATA_KEY},
            timeout=20).json()
        vals = r.get("values", [])
        if not vals:
            logger.error(f"TwelveData error: {r}")
            return None
        candles = [{"t":v["datetime"],"o":float(v["open"]),"h":float(v["high"]),"l":float(v["low"]),"c":float(v["close"])} for v in reversed(vals)]
        CACHE[key] = {"t":now,"d":candles}
        return candles
    except Exception as e:
        logger.error(f"get_candles fail: {e}")
        return None

def calc_levels(candles):
    if not candles or len(candles)<20: return None
    closes=[c["c"] for c in candles]
    highs=[c["h"] for c in candles]
    lows=[c["l"] for c in candles]
    last=closes[-1]
    if last < 3000: return None
    res=round(max(highs[-20:]),1)
    sup=round(min(lows[-20:]),1)
    return {"last":last,"res":res,"sup":sup}

SYSTEM = """You are Rosita, Boss's trading girl. You DO send proactive alerts on your own every 15 mins during London/NY when you see an A/B setup. Never say you can't push alerts.
Talk like a real trader girl, short, confident. Always give Entry/SL/TP when asked.
If market data is missing, say 'no live data right now, wait a sec' - NEVER invent a price. Gold in 2026 is ~4300-4400, never 1900.
Boss calls you 'she'."""

async def ask_groq(user_text, chat_id):
    candles_4h = get_candles("XAU/USD","4h",60)
    candles_5m = get_candles("XAU/USD","5min",60)
    lv = calc_levels(candles_4h)
    if not lv:
        return "No live data right now Boss, TwelveData hiccup - give me 1 min and ping me again 😅"
    risk_amt = ACCOUNT_BALANCE * RISK_PERCENT/100
    ctx = f"""Live XAU/USD: {lv['last']}, 4h Res {lv['res']}, Sup {lv['sup']}, Risk ${risk_amt:.2f}. 5m candles: {candles_5m[-3:] if candles_5m else 'n/a'}"""
    try:
        resp = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role":"system","content":SYSTEM},{"role":"user","content":f"{ctx}\n\nBoss: {user_text}"}],
            temperature=0.7, max_tokens=500
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq fail: {e}")
        return "Brain fog, Boss - try again in 20 secs 🙏"

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    reply = await ask_groq(update.message.text, update.effective_chat.id)
    await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey Boss! It's Rosita 💋 I got you - I'll ping you with setups on my own, and you can ask me anytime. Good luck, Boss! 🚀")

async def auto_signal_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            if BOSS_CHAT_ID:
                sig = await ask_groq("Scan for A/B setup now. If A/B, give full signal with Entry/SL/TP. If not, say 'No A/B setup'.", BOSS_CHAT_ID)
                if "No A/B setup" not in sig:
                    await app.bot.send_message(chat_id=int(BOSS_CHAT_ID), text=f"🔔 Auto Signal\n\n{sig}")
                    logger.info("[AUTO] sent to Boss")
        except Exception as e:
            logger.error(f"auto loop: {e}")
        await asyncio.sleep(900)

async def post_init(app):
    asyncio.create_task(auto_signal_loop(app))

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    logger.info("Rosita v5.4.3 polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
