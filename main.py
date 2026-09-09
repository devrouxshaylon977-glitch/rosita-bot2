import os, asyncio, logging, requests, threading, json
from datetime import datetime, timezone
from collections import defaultdict, deque
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Rosita")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TWELVEDATA_KEY = os.getenv("TWELVEDATA_KEY", "")
BOSS_CHAT_ID = os.getenv("BOSS_CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000") or 10000)
MEM_FILE = "rosita_memory.json"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
CACHE = {}
NEWS_CACHE = {"t":0,"d":[]}
HISTORY = defaultdict(lambda: deque(maxlen=12))

try:
    with open(MEM_FILE, "r") as f: LONG_MEM = json.load(f)
except: LONG_MEM = {}
def save_mem():
    try:
        with open(MEM_FILE, "w") as f: json.dump(LONG_MEM, f)
    except Exception as e: logger.error(e)

web = Flask(__name__)
@web.route("/")
def health(): return "Rosita alive", 200
@web.route("/health")
def health2(): return "ok", 200
def run_web(): web.run(host="0.0.0.0", port=PORT, use_reloader=False)
threading.Thread(target=run_web, daemon=True).start()

def get_candles(symbol="XAU/USD", interval="4h", n=200):
    key = f"{symbol}_{interval}"
    now = datetime.now().timestamp()
    if key in CACHE and now - CACHE[key]["t"] < 300:
        return CACHE[key]["d"]
    try:
        r = requests.get("https://api.twelvedata.com/time_series",
            params={"symbol": symbol, "interval": interval, "outputsize": n, "apikey": TWELVEDATA_KEY},
            timeout=20).json()
        vals = r.get("values", [])
        if not vals: return None
        candles=[]
        for v in reversed(vals):
            try: candles.append({"t":v["datetime"],"o":float(v["open"]),"h":float(v["high"]),"l":float(v["low"]),"c":float(v["close"])})
            except: continue
        CACHE[key]={"t":now,"d":candles}
        return candles
    except Exception as e:
        logger.error(e); return None

def get_news_warning():
    now_ts = datetime.now(timezone.utc).timestamp()
    if now_ts - NEWS_CACHE["t"] < 1800:
        events = NEWS_CACHE["d"]
    else:
        try:
            r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=15).json()
            events = r; NEWS_CACHE["t"] = now_ts; NEWS_CACHE["d"] = events
        except Exception as e:
            logger.error(f"news fail: {e}"); return ""
    warnings=[]; now = datetime.now(timezone.utc)
    for ev in events:
        try:
            if ev.get("country")!= "USD": continue
            if ev.get("impact")!= "High": continue
            dt = datetime.fromisoformat(ev["date"].replace("Z","+00:00"))
            diff_min = (dt - now).total_seconds()/60
            if -30 <= diff_min <= 60:
                when = "in "+str(int(diff_min))+"m" if diff_min>0 else str(int(abs(diff_min)))+"m ago"
                warnings.append(f"{ev['title']} ({when})")
        except: continue
    if warnings:
        return "⚠️ HIGH IMPACT USD NEWS: " + ", ".join(warnings[:3]) + " — sit out Shay 🫦 👀"
    return ""

def ema(values, period):
    k=2/(period+1); e=values[0]; out=[]
    for v in values:
        e=v*k+e*(1-k); out.append(e)
    return out

def do_backtest(candles):
    if not candles or len(candles)<50: return None
    closes=[c["c"] for c in candles]
    e9=ema(closes,9); e21=ema(closes,21)
    wins=losses=total=0
    for i in range(21, len(candles)-10):
        prev_bull=e9[i-1]>e21[i-1]; curr_bull=e9[i]>e21[i]
        if not prev_bull and curr_bull:
            entry=closes[i]; sl=min(c["l"] for c in candles[i-3:i+1]); risk=entry-sl
            if risk<=0: continue
            tp=entry+risk*2; total+=1; win=False
            for j in range(i+1, min(i+11,len(candles))):
                if candles[j]["l"]<=sl: win=False; break
                if candles[j]["h"]>=tp: win=True; break
            if win: wins+=1
            else: losses+=1
        elif prev_bull and not curr_bull:
            entry=closes[i]; sl=max(c["h"] for c in candles[i-3:i+1]); risk=sl-entry
            if risk<=0: continue
            tp=entry-risk*2; total+=1; win=False
            for j in range(i+1, min(i+11,len(candles))):
                if candles[j]["h"]>=sl: win=False; break
                if candles[j]["l"]<=tp: win=True; break
            if win: wins+=1
            else: losses+=1
    if total==0: return None
    return {"trades":total,"wins":wins,"losses":losses,"winrate":round(wins/total*100,1)}

SYSTEM="""You are Rosita, Shay's personal trading girl, mentor and market analyst.
You CAN send proactive auto alerts via the bot loop. Never say you can't push alerts or can't message on your own. Never say you can't watch markets.
Always call him "Shay". Always use 🫦 👀 💕 in every reply, never other emojis.
Talk like sharp, flirty, confident Joburg trading girl, short, casual, no-BS, professional not romantic.
You know trading fully. Gold 2026 ~4300-4400. Never invent live prices.
If news warning is given, respect it and tell Shay to sit out.
"""

async def ask_groq(user_text, chat_id):
    cid=str(chat_id); HISTORY[cid].append({"role":"user","content":user_text})
    mem=LONG_MEM.get(cid,"")
    if not client: return "No brain yet Shay 🫦 👀 add GROQ_API_KEY 💕"
    messages=[{"role":"system","content":SYSTEM+f"\n[Memory] {mem}"}]
    for m in list(HISTORY[cid])[-10:]: messages.append(m)
    try:
        r=client.chat.completions.create(model="openai/gpt-oss-20b",messages=messages,temperature=0.7,max_tokens=600)
        txt=r.choices[0].message.content.strip() or "I'm here Shay 🫦 👀 💕"
        HISTORY[cid].append({"role":"assistant","content":txt}); return txt
    except Exception as e:
        logger.error(e); return "Brain fog Shay 🫦 👀 try again 💕"

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text_raw=update.message.text.strip(); low=text_raw.lower()
    if low in ["hi","hello","hey","yo"]:
        await update.message.reply_text("Hey Shay 🫦 👀 I'm here 💕 I auto-alert scalps now"); return
    if low.startswith("remember "):
        cid=str(update.effective_chat.id); LONG_MEM[cid]=(LONG_MEM.get(cid,"")+" "+text_raw[9:]).strip()[-1000:]; save_mem()
        await update.message.reply_text("Got it Shay 🫦 👀 I'll remember 💕"); return
    if low=="what do you remember":
        await update.message.reply_text(f"I remember Shay 🫦 👀: {LONG_MEM.get(str(update.effective_chat.id),'nothing')} 💕"); return
    if "news" in low:
        w=get_news_warning()
        await update.message.reply_text(w if w else "No high-impact USD news in next 60m Shay 🫦 👀 you're clear 💕")
        return
    if low.startswith("backtest"):
        tf="1h"
        if "15m" in low or "15min" in low: tf="15min"
        elif "30m" in low: tf="30min"
        elif "4h" in low: tf="4h"
        elif "5m" in low: tf="5min"
        await update.message.reply_text(f"Running real backtest Shay 🫦 👀 {tf}...")
        candles=get_candles("XAU/USD",tf,200); res=do_backtest(candles)
        if not res: await update.message.reply_text("Not enough data Shay 🫦 👀 try later 💕"); return
        msg=(f"Done Shay 🫦 👀 Backtest {tf} 💕\nTrades: {res['trades']}\nWinrate: {res['winrate']}%\n"
             f"{'Solid keep it' if res['winrate']>=55 else 'Risky, filter more'} 🫦 💕")
        await update.message.reply_text(msg); return
    if "alert" in low and "setup" in low:
        await update.message.reply_text("Yes Shay 🫦 👀 I got you — I'll auto-alert you on 15m/5m scalp A/B setups every 5m 💕")
        return
    news_w=get_news_warning()
    prompt=text_raw + (f"\n\n[{news_w}]" if news_w else "")
    reply=await ask_groq(prompt, update.effective_chat.id)
    await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey Shay! It's Rosita 🫦 👀 I auto-alert scalps now 💕")

async def auto_signal_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            if BOSS_CHAT_ID.strip():
                news_w=get_news_warning()
                if news_w:
                    await app.bot.send_message(chat_id=int(BOSS_CHAT_ID), text=f"{news_w} 💕")
                else:
                    c15=get_candles("XAU/USD","15min",60)
                    c5=get_candles("XAU/USD","5min",60)
                    if c15 and c5:
                        last=c15[-1]["c"]
                        sig=await ask_groq(f"Scalp scan XAU/USD at {last} 15m/5m. If A/B setup give Entry/SL/TP else say 'No A/B setup'.", BOSS_CHAT_ID)
                        if "No A/B setup" not in sig:
                            await app.bot.send_message(chat_id=int(BOSS_CHAT_ID), text=f"👀 Scalp Signal 🫦\n\n{sig} 💕")
        except Exception as e: logger.error(e)
        await asyncio.sleep(300)

async def post_init(app): asyncio.create_task(auto_signal_loop(app))

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_msg))
    app.run_polling()
if __name__=="__main__": main()
