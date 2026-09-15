import os, asyncio, logging, requests, threading, json
from datetime import datetime, timezone
from collections import defaultdict, deque
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq

# FIX for Python 3.14.3 Render
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Swarm17")

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
    except: pass

web = Flask(__name__)
@web.route("/")
def h(): return "Swarm v17.1 Rosita+Harleen+Magna - Alive", 200
def run_flask():
    web.run(host="0.0.0.0", port=PORT, use_reloader=False)
threading.Thread(target=run_flask, daemon=True).start()

def get_candles(symbol="XAU/USD", interval="4h", n=200):
    key=f"{symbol}_{interval}"; now=datetime.now().timestamp()
    if key in CACHE and now-CACHE[key]["t"]<300: return CACHE[key]["d"]
    try:
        r=requests.get("https://api.twelvedata.com/time_series",
            params={"symbol":symbol,"interval":interval,"outputsize":n,"apikey":TWELVEDATA_KEY},timeout=20).json()
        vals=r.get("values",[])
        if not vals: return None
        candles=[{"t":v["datetime"],"o":float(v["open"]),"h":float(v["high"]),"l":float(v["low"]),"c":float(v["close"])} for v in reversed(vals)]
        CACHE[key]={"t":now,"d":candles}
        return candles
    except: return None

def get_live_price(): c=get_candles("XAU/USD","5min",5); return c[-1]["c"] if c else None
def ema(values, period):
    k=2/(period+1); e=values[0]; out=[]
    for v in values: e=v*k+e*(1-k); out.append(e)
    return out
def tf_bias(candles):
    if not candles or len(candles)<22: return "unknown"
    closes=[c["c"] for c in candles]; e9=ema(closes,9); e21=ema(closes,21)
    return "bullish" if e9[-1]>e21[-1] else "bearish"
def fib_levels(candles, lookback=50):
    if not candles or len(candles)<lookback: return None
    window=candles[-lookback:]; sh=max(c["h"] for c in window); sl=min(c["l"] for c in window); diff=sh-sl
    if diff<=0: return None
    return {"high":sh,"low":sl,"0.618":sh-diff*0.618,"0.65":sh-diff*0.65,"0.705":sh-diff*0.705,"0.79":sh-diff*0.79}

def get_news_warning():
    now_ts=datetime.now(timezone.utc).timestamp()
    if now_ts-NEWS_CACHE["t"]<1800: events=NEWS_CACHE["d"]
    else:
        try: r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=15).json(); events=r; NEWS_CACHE["t"]=now_ts; NEWS_CACHE["d"]=events
        except: return ""
    warns=[]; now=datetime.now(timezone.utc)
    for ev in events:
        try:
            if ev.get("country")!="USD" or ev.get("impact")!="High": continue
            dt=datetime.fromisoformat(ev["date"].replace("Z","+00:00")); diff=(dt-now).total_seconds()/60
            if -30<=diff<=60: warns.append(f"{ev['title']} ({int(diff)}m)")
        except: continue
    return "⚠️ HIGH IMPACT USD: "+",".join(warns[:3])+" — Harleen says sit out" if warns else ""

SYSTEM = """You are SWARM v17.1 - Three girls in one brain. ALWAYS include 🫦 👀 💕
**ROSITA (Boss/Alice)** - Top-down: 4h bias -> 1h bias -> 15m structure -> 5m entry.
**HARLEEN QUINZEL (Risk/Azariah)** - Veto. Checks news, session killzones London 8-11am EST, NY 1:30-4pm EST. Can VETO. If news warning present, MUST veto. Manual only.
**MAGNA (Sniper/Nora)** - Reversal: sweep, BOS/CHoCH, OB, FVG, Fib OTE 61.8-79%.
Gold 2026 ~4300-4400. Use live price given.
Format if valid:
Bias 4h/1h: [Rosita]
Harleen Verdict: [PASS or VETO + reason]
Magna Snipe: [OTE / sweep / FVG]
Direction: Long/Short
Entry: x.xx
SL: x.xx
TP1-TP10 Ladder: [list 10 TPs]
Reason: Setup A/B/C + confluences
Confluences: bullet list 3-5
If NO valid setup: No A/B/C setup - Harleen vetoed / no confluence
Educational only, manual execution. Always call user Shay.
"""

async def ask_groq(user_text, chat_id):
    cid=str(chat_id); HISTORY[cid].append({"role":"user","content":user_text})
    mem=LONG_MEM.get(cid,"")
    if not client: return "No brain yet Shay 🫦 👀 add GROQ_API_KEY 💕"
    msgs=[{"role":"system","content":SYSTEM+f"\n[Memory] {mem}"}]
    for m in list(HISTORY[cid])[-10:]: msgs.append(m)
    try:
        # FIXED MODEL - this one works 100% on Groq
        r=client.chat.completions.create(model="llama-3.1-8b-instant",messages=msgs,temperature=0.6,max_tokens=900)
        txt=r.choices[0].message.content.strip(); HISTORY[cid].append({"role":"assistant","content":txt}); return txt
    except Exception as e:
        logger.error(e)
        return f"Brain fog Shay 🫦 👀 {e} 💕"

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    low=update.message.text.lower().strip()
    if low in ["hi","hello","hey","yo"]:
        await update.message.reply_text("Hey Shay 🫦 👀 Swarm v17.1 online — Rosita + Harleen + Magna manual mode 💕"); return
    if low.startswith("remember "):
        LONG_MEM[str(update.effective_chat.id)]=(LONG_MEM.get(str(update.effective_chat.id),"")+" "+update.message.text[9:]).strip()[-1000:]; save_mem()
        await update.message.reply_text("Got it Shay 🫦 👀 I'll remember 💕"); return
    if "news" in low:
        w=get_news_warning(); await update.message.reply_text(w if w else "No high-impact USD in next 60m - Harleen says clear 🫦 👀 💕"); return
    if ("analyze" in low and "gold" in low) or low in ["signal","scalp","analyze gold","gold","xau"]:
        await update.message.reply_text("Swarm scanning Shay 🫦 👀 Rosita + Harleen + Magna debating...")
        c4h=get_candles("XAU/USD","4h",50); c1h=get_candles("XAU/USD","1h",50); c15=get_candles("XAU/USD","15min",60); c5=get_candles("XAU/USD","5min",20)
        if c4h and c1h and c15 and c5:
            ctx_top=f"4h {tf_bias(c4h)} @ {c4h[-1]['c']:.2f} | 1h {tf_bias(c1h)} @ {c1h[-1]['c']:.2f} | 15m {tf_bias(c15)} @ {c15[-1]['c']:.2f} | 5m {c5[-1]['c']:.2f}"
        else: ctx_top="partial data"
        fib=fib_levels(c15,50)
        if fib: ctx_top+=f" | Fib H {fib['high']:.2f} L {fib['low']:.2f} OTE 61.8 {fib['0.618']:.2f} 65 {fib['0.65']:.2f} 70.5 {fib['0.705']:.2f} 79 {fib['0.79']:.2f}"
        news_w=get_news_warning()
        sig=await ask_groq(f"Top-down XAU/USD scalp. {ctx_top}. News: {news_w}. Live {get_live_price()}. Do Rosita->Harleen->Magna debate then final format.", update.effective_chat.id)
        await update.message.reply_text(sig); return
    p=get_live_price(); price_ctx=f"\n[Live XAU/USD: {p:.2f}]" if p else ""
    reply=await ask_groq(update.message.text+price_ctx, update.effective_chat.id)
    await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Rosita + Harleen Quinzel + Magna online 🫦 👀 Manual signals only, I don't auto-trade 💕\nType: analyze gold")

async def auto_signal_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            if BOSS_CHAT_ID.strip():
                hr=datetime.now(timezone.utc).hour
                if hr>=21 or hr<5:
                    await asyncio.sleep(300); continue
                if get_news_warning():
                    await asyncio.sleep(1800); continue
                c15=get_candles("XAU/USD","15min",60)
                if c15:
                    last=c15[-1]["c"]
                    sig=await ask_groq(f"Swarm auto-scan XAU/USD at {last}. Manual signal only. If no setup reply exactly 'No A/B/C setup'", BOSS_CHAT_ID)
                    if "Entry:" in sig and "SL:" in sig and "No A/B/C" not in sig:
                        await app.bot.send_message(chat_id=int(BOSS_CHAT_ID), text=f"{sig}\n\nManual only 💕")
        except Exception as e: logger.error(e)
        await asyncio.sleep(300)

async def post_init(app): asyncio.create_task(auto_signal_loop(app))

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_msg))
    print("Swarm v17.1 FIXED model llama-3.1-8b-instant starting...")
    app.run_polling()

if __name__=="__main__":
    main()
