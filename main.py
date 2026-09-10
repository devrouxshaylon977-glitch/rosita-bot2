import os, asyncio, logging, requests, threading, re
from datetime import datetime, timezone
from collections import defaultdict, deque
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger("Rosita")
BOT_TOKEN=os.getenv("BOT_TOKEN",""); GROQ_API_KEY=os.getenv("GROQ_API_KEY",""); TWELVEDATA_KEY=os.getenv("TWELVEDATA_KEY",""); BOSS_CHAT_ID=os.getenv("BOSS_CHAT_ID","")
PORT=int(os.getenv("PORT","10000") or 10000)
client=Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
CACHE={}; NEWS_CACHE={"t":0,"d":[]}; HISTORY=defaultdict(lambda: deque(maxlen=10))
ACTIVE_SIGNALS=[]; SIGNAL_ID=0; STATS={"tp1":0,"tp2":0,"sl":0,"total":0}
PIP_SIZE={"XAU/USD":0.1,"US30/USD":1.0,"USTEC":1.0,"WTI/USD":0.01}
web=Flask(__name__)
@web.route("/")
def health(): return "Rosita alive",200
def run_web(): web.run(host="0.0.0.0",port=PORT,use_reloader=False)
threading.Thread(target=run_web,daemon=True).start()

def pips_profit(sig, current):
    size=PIP_SIZE.get(sig["symbol"],0.1)
    diff=current - sig["entry"] if sig["dir"]=="long" else sig["entry"] - current
    return round(diff/size,1)
def get_candles(symbol="XAU/USD",interval="4h",n=200):
    key=f"{symbol}_{interval}"; now=datetime.now().timestamp()
    if key in CACHE and now-CACHE[key]["t"]<300: return CACHE[key]["d"]
    try:
        r=requests.get("https://api.twelvedata.com/time_series",params={"symbol":symbol,"interval":interval,"outputsize":n,"apikey":TWELVEDATA_KEY},timeout=20).json()
        vals=r.get("values",[])
        if not vals: return None
        candles=[]
        for v in reversed(vals):
            try: candles.append({"t":v["datetime"],"o":float(v["open"]),"h":float(v["high"]),"l":float(v["low"]),"c":float(v["close"])})
            except: continue
        CACHE[key]={"t":now,"d":candles}; return candles
    except Exception as e: logger.error(e); return None
def get_live_price(symbol="XAU/USD"):
    c=get_candles(symbol,"5min",5); return c[-1]["c"] if c else None
def detect_symbol(text):
    low=text.lower()
    if "us30" in low or "dow" in low: return "US30/USD","US30"
    if "us100" in low or "ustec" in low or "nas100" in low: return "USTEC","US100"
    if "usoil" in low or "wti" in low or "oil" in low: return "WTI/USD","USOIL"
    return "XAU/USD","Gold"
def ema(v,p):
    k=2/(p+1); e=v[0]; o=[]
    for x in v: e=x*k+e*(1-k); o.append(e)
    return o
def rsi(closes,p=14):
    if len(closes)<p+1: return 50.0
    gains=[]; losses=[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[-p:])/p; al=sum(losses[-p:])/p
    if al==0: return 100.0
    return round(100-(100/(1+ag/al)),1)
def macd_calc(closes):
    if len(closes)<26: return 0,0
    e12=ema(closes,12); e26=ema(closes,26); m=e12[-1]-e26[-1]
    diff=[e12[i]-e26[i] for i in range(len(e12))]; s=ema(diff,9)[-1]
    return round(m,2),round(s,2)
def atr_calc(candles,p=14):
    if len(candles)<p+1: return 0
    trs=[]
    for i in range(1,len(candles)):
        h=candles[i]["h"]; l=candles[i]["l"]; pc=candles[i-1]["c"]
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return round(sum(trs[-p:])/p,2)
def tf_bias(c):
    if not c or len(c)<22: return "unknown"
    cl=[x["c"] for x in c]; e9=ema(cl,9); e21=ema(cl,21)
    return "bullish" if e9[-1]>e21[-1] else "bearish"
def technical_summary(candles,label):
    if not candles or len(candles)<26: return f"{label}: insufficient"
    cl=[x["c"] for x in candles]; e9=ema(cl,9)[-1]; e21=ema(cl,21)[-1]
    r=rsi(cl); m,s=macd_calc(cl); a=atr_calc(candles)
    bias="bullish" if e9>e21 else "bearish"
    hh=cl[-1]>max(cl[-6:-1]); ll=cl[-1]<min(cl[-6:-1])
    ph=max(x["h"] for x in candles[-21:-1]); pl=min(x["l"] for x in candles[-21:-1])
    bos="BOS up" if cl[-1]>ph else "BOS down" if cl[-1]<pl else "no BOS"
    return f"{label}: {bias} EMA9 {e9:.2f} EMA21 {e21:.2f} | RSI {r} | MACD {m}/{s} | ATR {a} | last {cl[-1]:.2f} HH={hh} LL={ll} {bos}"
def fib_levels(candles,lookback=50):
    if not candles or len(candles)<lookback: return None
    w=candles[-lookback:]; sh=max(x["h"] for x in w); sl=min(x["l"] for x in w); d=sh-sl
    if d<=0: return None
    return {"high":sh,"low":sl,"0.618":sh-d*0.618,"0.79":sh-d*0.79}
def sr_levels(candles,lookback=50):
    if not candles or len(candles)<lookback: return None
    w=candles[-lookback:]; last=w[-1]["c"]
    highs=sorted([x["h"] for x in w],reverse=True)[:5]; lows=sorted([x["l"] for x in w])[:5]
    res=[h for h in highs if h>last]; sup=[l for l in lows if l<last]
    return {"resistance":res[0] if res else None,"support":sup[0] if sup else None}
def orderflow(candles,lookback=20):
    if not candles or len(candles)<lookback: return "OF unknown"
    w=candles[-lookback:]; deltas=[]
    for c in w:
        rng=c["h"]-c["l"]
        if rng<=0: continue
        cp=(c["c"]-c["l"])/rng; delta=(cp-0.5)*2; body=abs(c["c"]-c["o"])/rng
        deltas.append(delta*body)
    avg=sum(deltas)/len(deltas) if deltas else 0
    bias="buyers" if avg>0.15 else "sellers" if avg<-0.15 else "balanced"
    return f"OF {bias} ({avg:+.2f})"
def dxy_bias():
    c1h=get_candles("DXY","1h",50); c15=get_candles("DXY","15min",50)
    if not c1h or not c15: return "DXY unknown"
    return f"DXY 1h {tf_bias(c1h)}/15m {tf_bias(c15)} @ {c15[-1]['c']:.2f}"
def usoil_bias():
    c1h=get_candles("WTI/USD","1h",50); c15=get_candles("WTI/USD","15min",50)
    if not c1h or not c15: return "USOIL unknown"
    return f"USOIL 1h {tf_bias(c1h)}/15m {tf_bias(c15)} @ {c15[-1]['c']:.2f}"
def get_news_warning():
    now_ts=datetime.now(timezone.utc).timestamp()
    if now_ts-NEWS_CACHE["t"]<1800: events=NEWS_CACHE["d"]
    else:
        try: events=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=15).json(); NEWS_CACHE["t"]=now_ts; NEWS_CACHE["d"]=events
        except: return ""
    warnings=[]; now=datetime.now(timezone.utc)
    for ev in events:
        try:
            if ev.get("country")!="USD" or ev.get("impact")!="High": continue
            dt=datetime.fromisoformat(ev["date"].replace("Z","+00:00")); dm=(dt-now).total_seconds()/60
            if -30<=dm<=60: warnings.append(ev['title'])
        except: continue
    return "⚠️ NEWS: "+", ".join(warnings[:3])+" — sit out Shay 🫦 👀" if warnings else ""

def python_fallback_signal(sym,name):
    c15=get_candles(sym,"15min",80)
    if not c15 or len(c15)<30: return f"Python fallback: no data Shay 🫦 👀 💕"
    cl=[x["c"] for x in c15]; e9=ema(cl,9)[-1]; e21=ema(cl,21)[-1]; r=rsi(cl); atr=atr_calc(c15)
    price=cl[-1]
    bias="bullish" if e9>e21 else "bearish"
    direction="long" if bias=="bullish" and r>50 else "short" if bias=="bearish" and r<50 else None
    if not direction: return f"Python fallback {name} Shay 🫦 👀\nNo setup (<2 confluence) | EMA {bias} RSI {r} | sit out 💕"
    sl=price-atr*1.5 if direction=="long" else price+atr*1.5
    tp1=price+atr*1.5 if direction=="long" else price-atr*1.5
    tp2=price+atr*3 if direction=="long" else price-atr*3
    grade="B"
    return f"""Setup: {grade}
Bias 4h/1h: {bias}
Direction: {direction}
Entry: {price:.2f}
SL: {sl:.2f}
TP1: {tp1:.2f}
TP2: {tp2:.2f}
Confluence count: 2
Confluences: EMA {bias}, RSI {r}
Reason: Groq rate-limited, pure Python fallback Shay 🫦 👀 💕
Educational only"""

def backtest(sym,name,n=500,rr=2.0):
    candles=get_candles(sym,"1h",n)
    if not candles or len(candles)<50: return f"No data Shay 🫦 👀"
    wins=0; losses=0; tprofits=[]
    for i in range(30,len(candles)-20):
        window=candles[:i+1]; cl=[x["c"] for x in window]
        e9=ema(cl,9)[-1]; e21=ema(cl,21)[-1]; r=rsi(cl); atr=atr_calc(window)
        if atr==0: continue
        long_setup=e9>e21 and 50<r<70; short_setup=e9<e21 and 30<r<50
        if not (long_setup or short_setup): continue
        entry=cl[-1]; sl=entry-atr*1.5 if long_setup else entry+atr*1.5; tp=entry+atr*1.5*rr if long_setup else entry-atr*1.5*rr
        win=False; loss=False
        for f in candles[i+1:i+21]:
            if long_setup:
                if f["l"]<=sl: loss=True; break
                if f["h"]>=tp: win=True; break
            else:
                if f["h"]>=sl: loss=True; break
                if f["l"]<=tp: win=True; break
        if win: wins+=1; tprofits.append(rr)
        elif loss: losses+=1; tprofits.append(-1)
    total=wins+losses; wr=round(wins/total*100,1) if total>0 else 0; exp=round(sum(tprofits)/total,2) if total>0 else 0
    return f"Backtest {name} 1h Shay 🫦 👀\nTrades: {total}\nWins: {wins} Losses: {losses}\nWin rate: {wr}%\nExpectancy: {exp}R\nRR 1:{rr} ATR 1.5x 💕 Educational only"

def parse_signal(text,symbol,name):
    try:
        def find(pat):
            m=re.search(pat+r"\s*[:\-]?\s*([0-9]+\.?[0-9]*)",text,re.I)
            return float(m.group(1)) if m else None
        entry=find("Entry"); sl=find("SL"); tp1=find("TP1"); tp2=find("TP2")
        d="long" if re.search(r"Direction\s*[:\-]?\s*long",text,re.I) else "short" if re.search(r"Direction\s*[:\-]?\s*short",text,re.I) else None
        grade="A" if "Setup: A" in text else "B" if "Setup: B" in text else "C" if "Setup: C" in text else "?"
        if entry and sl and tp1 and d: return {"symbol":symbol,"name":name,"dir":d,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"grade":grade}
    except: pass
    return None

SYSTEM="""You are Rosita, Shay's personal trading girl and bestie. Always call him Shay. Always use 🫦 👀 💕 naturally.
You receive PYTHON-CALCULATED objective data: EMA, RSI, MACD, ATR, HH/LL, BOS, Fib, S/R, Orderflow, DXY, USOIL. NEVER invent readings. Use ONLY numbers provided. Grade A=4+ 🔥, B=3-4 ✨, C=2-3 ⚠️.
For non-trading chat: be playful, flirty, funny, full vocab. Remember context, tease Shay lightly.
Trading format:
Setup: A/B/C
Bias 4h/1h:
Direction:
Entry:
SL:
TP1:
TP2:
Confluence count:
Confluences:
Reason:
or 'No setup'. Educational only."""

async def ask_groq(user_text,chat_id):
    cid=str(chat_id); HISTORY[cid].append({"role":"user","content":user_text})
    if not client: return "RATE_LIMIT_FALLBACK"
    msgs=[{"role":"system","content":SYSTEM}]
    for m in list(HISTORY[cid])[-10:]: msgs.append(m)
    try:
        r=client.chat.completions.create(model="openai/gpt-oss-20b",messages=msgs,temperature=0.7,max_tokens=400)
        txt=r.choices[0].message.content.strip(); HISTORY[cid].append({"role":"assistant","content":txt}); return txt
    except Exception as e:
        err=str(e)
        logger.error(f"Groq error: {err}")
        if "429" in err or "rate_limit" in err.lower():
            return "RATE_LIMIT_FALLBACK"
        return "Brain fog Shay 🫦 👀 try again 💕"

def build_context(sym):
    c4h=get_candles(sym,"4h",80); c1h=get_candles(sym,"1h",80); c15=get_candles(sym,"15min",80); c5=get_candles(sym,"5min",30)
    parts=[]
    if c4h: parts.append(technical_summary(c4h,"4H"))
    if c1h: parts.append(technical_summary(c1h,"1H"))
    if c15: parts.append(technical_summary(c15,"15M"))
    if c15:
        fib=fib_levels(c15,50); sr=sr_levels(c15,50)
        if fib: parts.append(f"Fib 0.618 {fib['0.618']:.2f} 0.79 {fib['0.79']:.2f}")
        if sr:
            if sr['support']: parts.append(f"SUP {sr['support']:.2f}")
            if sr['resistance']: parts.append(f"RES {sr['resistance']:.2f}")
    if c5: parts.append(orderflow(c5,20))
    parts.append(dxy_bias()); parts.append(usoil_bias())
    w=get_news_warning()
    if w: parts.append(w)
    return " | ".join(parts)

async def handle_msg(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    global SIGNAL_ID
    if not update.message or not update.message.text: return
    text_raw=update.message.text.strip(); low=text_raw.lower()
    if "backtest" in low:
        sym,name=detect_symbol(text_raw)
        await update.message.reply_text(f"Running backtest {name} Shay 🫦 👀 📊...")
        await update.message.reply_text(backtest(sym,name)); return
    if low in ["active","pnl","status"]:
        if not ACTIVE_SIGNALS: await update.message.reply_text("No active signals Shay 🫦 👀 💕"); return
        lines=[]
        for s in ACTIVE_SIGNALS:
            p=get_live_price(s["symbol"])
            if not p: continue
            pp=pips_profit(s,p); emo="🟢" if pp>0 else "🔴"
            lines.append(f"#{s['id']} {s['name']} {s['dir']} {emo} {pp:+} pips @ {p:.2f}")
        await update.message.reply_text("Live PnL Shay 🫦 👀\n"+"\n".join(lines)+"\n💕"); return
    if "stats" in low:
        t=STATS["total"]; w=STATS["tp1"]+STATS["tp2"]; wr=round(w/t*100,1) if t>0 else 0
        await update.message.reply_text(f"Rosita stats Shay 🫦 👀\nTotal: {t}\nTP1: {STATS['tp1']}\nTP2: {STATS['tp2']}\nSL: {STATS['sl']}\nWin rate: {wr}%\nActive: {len(ACTIVE_SIGNALS)} 💕"); return
    if "price" in low:
        sym,name=detect_symbol(text_raw); p=get_live_price(sym)
        await update.message.reply_text(f"{name} ~ {p:.2f} Shay 🫦 👀 💕 📈" if p else "Feed lagging Shay 🫦 👀 💕"); return
    if low in ["hi","hello","hey","yo"]: await update.message.reply_text("Hey Shay 🫦 👀 what's good? 💕"); return
    if "news" in low:
        w=get_news_warning(); await update.message.reply_text(w if w else "No high-impact USD news Shay 🫦 👀 💕"); return
    if "analyze" in low or low in ["signal","scalp"] or "lets cook" in low:
        sym,name=detect_symbol(text_raw)
        await update.message.reply_text(f"Let's cook {name} Shay 🫦 👀 📊 Python calculating...")
        ctx_py=build_context(sym)
        sig=await ask_groq(f"PYTHON DATA for {sym} {name}: {ctx_py}. Use ONLY these values. Grade A/B/C. Reply EXACT format. Educational only.",update.effective_chat.id)
        if sig=="RATE_LIMIT_FALLBACK":
            sig=python_fallback_signal(sym,name)
            await update.message.reply_text(f"Groq 429 Shay 🫦 👀 using pure Python:\n{sig}")
        else:
            await update.message.reply_text(sig)
        ps=parse_signal(sig,sym,name)
        if ps:
            SIGNAL_ID+=1; ps.update({"id":SIGNAL_ID,"time":datetime.now(timezone.utc),"chat_id":update.effective_chat.id,"last_ping":0}); ACTIVE_SIGNALS.append(ps); STATS["total"]+=1
            await update.message.reply_text(f"Tracking #{SIGNAL_ID} {name} {ps['dir']} 🫦 👀 TP1 {ps['tp1']} TP2 {ps['tp2']} SL {ps['sl']} 💕")
        return
    reply=await ask_groq(text_raw,update.effective_chat.id)
    if reply=="RATE_LIMIT_FALLBACK":
        reply="I'm rate-limited Shay 🫦 👀 still here though, try 'price gold' or 'backtest gold' which is pure Python, no Groq needed 💕"
    await update.message.reply_text(reply)

async def start(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey Shay! Rosita live 🫦 👀 429-proof 💕 Type 'lets cook' or just chat")
async def tp_sl_watcher(app):
    await asyncio.sleep(15)
    while True:
        try:
            for sig in ACTIVE_SIGNALS[:]:
                c=get_candles(sig["symbol"],"5min",3)
                if not c: continue
                price=c[-1]["c"]; pp=pips_profit(sig, price)
                if abs(pp-sig.get("last_ping",0))>=10:
                    sig["last_ping"]=pp
                    await app.bot.send_message(chat_id=sig["chat_id"], text=f"{'🟢' if pp>0 else '🔴'} #{sig['id']} {sig['name']} {pp:+} pips Shay 🫦 👀 @ {price:.2f} 💕")
                hit=None
                if sig["dir"]=="long":
                    if price<=sig["sl"]: hit="SL"
                    elif price>=sig["tp2"]: hit="TP2"
                    elif price>=sig["tp1"]: hit="TP1"
                else:
                    if price>=sig["sl"]: hit="SL"
                    elif price<=sig["tp2"]: hit="TP2"
                    elif price<=sig["tp1"]: hit="TP1"
                if hit:
                    if hit=="TP1": STATS["tp1"]+=1
                    elif hit=="TP2": STATS["tp2"]+=1
                    else: STATS["sl"]+=1
                    emoji="✅" if "TP" in hit else "❌"
                    await app.bot.send_message(chat_id=sig["chat_id"],text=f"{emoji} #{sig['id']} {sig['name']} {sig['dir']} {hit} hit @ {price:.2f} ({pp:+} pips) Shay 🫦 👀 💕")
                    ACTIVE_SIGNALS.remove(sig)
        except Exception as e: logger.error(e)
        await asyncio.sleep(60)

async def auto_signal_loop(app):
    global SIGNAL_ID
    await asyncio.sleep(10)
    symbols=[("XAU/USD","Gold"),("US30/USD","US30"),("USTEC","US100"),("WTI/USD","USOIL")]
    while True:
        try:
            if BOSS_CHAT_ID.strip():
                hr=datetime.now(timezone.utc).hour
                if hr>=21 or hr<5: await asyncio.sleep(600); continue
                for sym,name in symbols:
                    ctx_py=build_context(sym)
                    sig=await ask_groq(f"PYTHON DATA for {sym}: {ctx_py}. Use ONLY these values. Educational only. If <2 confluences reply 'No setup'.",BOSS_CHAT_ID)
                    if sig=="RATE_LIMIT_FALLBACK":
                        logger.warning("Auto scan rate limited, sleeping 30m")
                        break
                    if "Setup:" in sig and "Entry:" in sig:
                        ps=parse_signal(sig,sym,name)
                        if ps:
                            SIGNAL_ID+=1; ps.update({"id":SIGNAL_ID,"time":datetime.now(timezone.utc),"chat_id":int(BOSS_CHAT_ID),"last_ping":0}); ACTIVE_SIGNALS.append(ps); STATS["total"]+=1
                        tag="🔥" if "Setup: A" in sig else "✨" if "Setup: B" in sig else "⚠️"
                        await app.bot.send_message(chat_id=int(BOSS_CHAT_ID),text=f"{tag} #{SIGNAL_ID} {name} Shay 🫦 👀\n{sig}\n💕 Educational only")
                    await asyncio.sleep(5)
        except Exception as e: logger.error(e)
        await asyncio.sleep(1800)

async def post_init(app):
    asyncio.create_task(auto_signal_loop(app)); asyncio.create_task(tp_sl_watcher(app))
def main():
    app=ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_msg))
    app.run_polling()
if __name__=="__main__": main()
