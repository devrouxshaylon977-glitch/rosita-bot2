import os, asyncio, logging, requests, threading, json
from datetime import datetime, timezone
from collections import defaultdict, deque
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Swarm18.3")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TWELVEDATA_KEY = os.getenv("TWELVEDATA_KEY", "")
BOSS_CHAT_ID = os.getenv("BOSS_CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000") or 10000)
MEM_FILE = "rosita_memory.json"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
CACHE = {}
NEWS_CACHE = {"t": 0, "d": []}
HISTORY = defaultdict(lambda: deque(maxlen=12))

try:
    with open(MEM_FILE, "r") as f: LONG_MEM = json.load(f)
except: LONG_MEM={}
def save_mem():
    try:
        with open(MEM_FILE, "w") as ff: json.dump(LONG_MEM, ff)
    except: pass

web = Flask(__name__)
@web.route("/")
def h(): return "Swarm v18.3 Telegram Only - Alive", 200
def run_web(): web.run(host="0.0.0.0", port=PORT, use_reloader=False)
threading.Thread(target=run_web, daemon=True).start()

SYM_MAP = {
 "gold":"XAU/USD","xau":"XAU/USD",
 "silver":"XAG/USD","xag":"XAG/USD",
 "us oil":"WTI/USD","wti":"WTI/USD","oil":"WTI/USD",
 "brent":"BRENT/USD",
 "euru":"EUR/USD","eurusd":"EUR/USD","eur":"EUR/USD",
 "ether":"ETH/USD","eth":"ETH/USD",
 "nas100":"NDX/USD","nas":"NDX/USD","ndx":"NDX/USD",
 "us30":"DJI/USD","dow":"DJI/USD","dji":"DJI/USD",
 "spx500":"SPX/USD","spx":"SPX/USD",
 "dxy":"DXY/USD","dollar":"DXY/USD"
}

def get_td_price(sym):
    try:
        r=requests.get("https://api.twelvedata.com/price",params={"symbol":sym,"apikey":TWELVEDATA_KEY},timeout=10).json()
        return float(r["price"])
    except: return None

def is_weekend_closed():
    now=datetime.now(timezone.utc); wd=now.weekday(); hr=now.hour
    if wd==4 and hr>=22: return True
    if wd==5: return True
    if wd==6 and hr<22: return True
    return False

def get_candles(symbol="XAU/USD", interval="4h", n=200):
    key=f"{symbol}_{interval}"; now_ts=datetime.now().timestamp()
    if key in CACHE and now_ts-CACHE[key]["t"]<300: return CACHE[key]["d"]
    try:
        r=requests.get("https://api.twelvedata.com/time_series",params={"symbol":symbol,"interval":interval,"outputsize":n,"apikey":TWELVEDATA_KEY},timeout=20).json()
        vals=r.get("values",[])
        if not vals: return None
        candles=[]
        for v in reversed(vals): candles.append({"t":v["datetime"],"o":float(v["open"]),"h":float(v["high"]),"l":float(v["low"]),"c":float(v["close"])})
        CACHE[key]={"t":now_ts,"d":candles}; return candles
    except: return None

def get_live_price(sym="XAU/USD"):
    c=get_candles(sym,"5min",5)
    if c: return c[-1]["c"]
    return get_td_price(sym)

def ema(values, period):
    k=2.0/(period+1); e=values[0]; out=[]
    for v in values: e=v*k+e*(1-k); out.append(e)
    return out
def tf_bias(c):
    if not c or len(c)<22: return "unknown"
    closes=[x["c"] for x in c]; e9=ema(closes,9); e21=ema(closes,21)
    return "bullish" if e9[-1]>e21[-1] else "bearish"
def fib_levels(candles, lookback=50):
    if not candles or len(candles)<lookback: return None
    w=candles[-lookback:]; sh=max(x["h"] for x in w); sl=min(x["l"] for x in w); d=sh-sl
    if d<=0: return None
    return {"high":sh,"low":sl,"0.618":sh-d*0.618,"0.65":sh-d*0.65,"0.705":sh-d*0.705,"0.79":sh-d*0.79}
def get_news_warning():
    now_ts=datetime.now(timezone.utc).timestamp()
    if now_ts-NEWS_CACHE["t"]<1800: events=NEWS_CACHE["d"]
    else:
        try: r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=15).json(); events=r; NEWS_CACHE["t"]=now_ts; NEWS_CACHE["d"]=events
        except: return ""
    warns=[]; now=datetime.now(timezone.utc)
    for ev in events:
        try:
            if ev.get("country")!="USD": continue
            if ev.get("impact")!="High": continue
            dt=datetime.fromisoformat(ev["date"].replace("Z","+00:00")); diff=(dt-now).total_seconds()/60
            if -30<=diff<=60: warns.append(f"{ev['title']} ({int(diff)}m)")
        except: continue
    if warns: return "HIGH IMPACT USD: "+",".join(warns[:3])+" - Harleen says sit out"
    return ""

SYSTEM="""You are SWARM v18.3 - Rosita + Harleen Quinzel + Magna. ALWAYS include emojis. Call user Shay.
Rosita Boss top-down 4h->1h->15m->5m.
Harleen Veto news/session/weekend.
Magna Sniper sweep/FVG/OTE 61.8-79%.
You can analyze GOLD SILVER US OIL BRENT EURU ETHER NAS100 US30 SPX500 DXY - use given symbol price.
Even on weekend, use last known price and analyze structure, say Market closed but structure shows...
If valid:
Bias 4h/1h: [Rosita]
Harleen Verdict: [PASS/VETO]
Magna Snipe: [OTE/sweep/FVG]
Direction: Long/Short
Entry: x.xx
SL: x.xx
TP1-TP10 Ladder: [10 TPs compact]
Reason: Setup A/B/C
Confluences: bullets
If no valid: No A/B/C setup - Harleen vetoed / no confluence
Manual only, educational.
"""

async def ask_groq(text, chat_id):
    cid=str(chat_id); HISTORY[cid].append({"role":"user","content":text}); mem=LONG_MEM.get(cid,"")
    if not client: return "No brain yet Shay add GROQ_API_KEY"
    msgs=[{"role":"system","content":SYSTEM+f"\n[Memory] {mem}"}]
    for m in list(HISTORY[cid])[-10:]: msgs.append(m)
    try:
        r=client.chat.completions.create(model="openai/gpt-oss-20b",messages=msgs,temperature=0.6,max_tokens=900)
        txt=r.choices[0].message.content.strip(); HISTORY[cid].append({"role":"assistant","content":txt}); return txt
    except Exception as e: logger.error(e); return "Brain fog Shay try again"

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    low=update.message.text.lower().strip()

    if low in ["hi","hello","hey","yo","gm"]:
        await update.message.reply_text("Hey Shay 💋 Swarm v18.3 online - old swarm Rosita + Harleen + Magna"); return
    if low.startswith("remember "):
        LONG_MEM[str(update.effective_chat.id)]=(LONG_MEM.get(str(update.effective_chat.id),"")+" "+update.message.text[9:]).strip()[-1000:]; save_mem()
        await update.message.reply_text("Got it Shay I'll remember"); return
    if "news" in low:
        w=get_news_warning()
        await update.message.reply_text(w if w else "No high-impact USD - Harleen clear 💋"); return

    # PRICE CHECK - works even on weekend
    if "price" in low or "current" in low:
        s="XAU/USD"; name="GOLD"
        for k,v in SYM_MAP.items():
            if k in low: s=v; name=k.upper(); break
        p=get_td_price(s) or get_live_price(s)
        c=get_candles(s,"5min",5)
        if c and not p: p=c[-1]["c"]
        if p:
            await update.message.reply_text(f"{name} {s} live {p:.2f} Shay 💋\n{'Weekend - last close' if is_weekend_closed() and 'XAU' in s else 'Market live'}")
        else:
            await update.message.reply_text(f"Can't fetch {name} now Shay, TwelveData limit - try again in 30s")
        # if they said current price of gold, also do full analysis after
        if "analyze" not in low:
            return

    # MULTI-ASSET ANALYZE
    found_sym=None; found_name="GOLD"
    for k,v in SYM_MAP.items():
        if k in low:
            found_sym=v; found_name=k.upper(); break
    if "analyze" in low or low in ["signal","scalp","analyze"] or found_sym:
        sym=found_sym if found_sym else "XAU/USD"
        name=found_name if found_sym else "GOLD"
        await update.message.reply_text(f"Swarm scanning Shay {name} {sym} - Rosita + Harleen + Magna debating... 💭")
        c4h=get_candles(sym,"4h",50); c1h=get_candles(sym,"1h",50); c15=get_candles(sym,"15min",60); c5=get_candles(sym,"5min",20)
        price=get_td_price(sym)
        if not price and c5: price=c5[-1]["c"]
        if not price and c15: price=c15[-1]["c"]
        if not price: price=0

        if c4h and c1h and c15:
            ctx_top=f"{name} {sym} Live {price:.2f} 4h {tf_bias(c4h)} @ {c4h[-1]['c']:.2f} | 1h {tf_bias(c1h)} @ {c1h[-1]['c']:.2f} | 15m {tf_bias(c15)} @ {c15[-1]['c']:.2f} | 5m {c5[-1]['c']:.2f if c5 else price:.2f}"
        else:
            # weekend fallback - don't say partial
            ctx_top=f"{name} {sym} Weekend/Partial - last known {price:.2f} 4h {tf_bias(c4h) if c4h else 'bullish'} | 1h {tf_bias(c1h) if c1h else 'bullish'} | 15m {tf_bias(c15) if c15 else 'neutral'} | 5m {price:.2f}"

        fib=fib_levels(c15,50) if c15 else None
        if fib: ctx_top+=f" | Fib H {fib['high']:.2f} L {fib['low']:.2f} OTE 61.8 {fib['0.618']:.2f} 70.5 {fib['0.705']:.2f} 79 {fib['0.79']:.2f}"
        sig=await ask_groq(f"{name} scalp {sym} {ctx_top} News:{get_news_warning()} Weekend:{is_weekend_closed()} Debate then final manual.",update.effective_chat.id)
        await update.message.reply_text(sig); return

    price=get_live_price(); pc=f"\n[Live XAU {price:.2f}]" if price else ""
    reply=await ask_groq(update.message.text+pc,update.effective_chat.id)
    await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Rosita + Harleen + Magna v18.3 online 💋 Telegram only - no desk\nTry: current price of gold / analyze us30 / analyze silver")

async def auto_signal_loop(app):
    was_closed=is_weekend_closed(); await asyncio.sleep(10)
    while True:
        try:
            if is_weekend_closed(): was_closed=True; await asyncio.sleep(3600); continue
            if was_closed:
                if not is_weekend_closed():
                    if BOSS_CHAT_ID.strip():
                        try: await app.bot.send_message(chat_id=int(BOSS_CHAT_ID),text="GM Shay Markets open - Rosita + Harleen + Magna awake 💋")
                        except: pass
                    was_closed=False
            if BOSS_CHAT_ID.strip():
                hr=datetime.now(timezone.utc).hour
                if hr>=21 or hr<5: await asyncio.sleep(300); continue
                if get_news_warning(): await asyncio.sleep(1800); continue
                c15=get_candles("XAU/USD","15min",60)
                if c15:
                    last=c15[-1]["c"]; sig=await ask_groq(f"Auto-scan XAU/USD at {last}. Manual only. If no setup reply exactly No A/B/C setup",BOSS_CHAT_ID)
                    if "Entry:" in sig and "SL:" in sig:
                        if "No A/B/C" not in sig: await app.bot.send_message(chat_id=int(BOSS_CHAT_ID),text=f"{sig}\n\nManual only")
        except Exception as e: logger.error(e)
        await asyncio.sleep(300)

async def post_init(app): asyncio.create_task(auto_signal_loop(app))

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
if __name__=="__main__": main()
