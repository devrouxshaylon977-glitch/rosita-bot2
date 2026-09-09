import os, requests, threading, time
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY")

app = Flask(__name__)
groq_client = Groq(api_key=GROQ_API_KEY)

@app.route('/')
def home():
    return "Rosita is awake."

cache = {"time": 0, "data": ""}
CACHE_SECONDS = 300
memory = {}

TRADING_WORDS = ["gold", "xau", "dxy", "dollar", "analyze", "analysis", "chart", "buy", "sell", "trade", "long", "short", "support", "resistance", "trend", "entry", "bias"]

def is_trading_question(text):
    t = text.lower()
    return any(w in t for w in TRADING_WORDS)

def get_candles(symbol, interval):
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol": symbol, "interval": interval,
            "outputsize": 20, "apikey": TWELVEDATA_KEY
        }, timeout=15).json()
        if "values" not in r:
            return f"\n{symbol} {interval}: API error {r.get('message','unknown')}\n"
        vals = r["values"][:10]
        out = f"\n{symbol} {interval} last 10 candles (newest first):\n"
        for v in vals:
            out += f"{v['datetime']} O:{v['open']} H:{v['high']} L:{v['low']} C:{v['close']}\n"
        return out
    except Exception as e:
        return f"\n{symbol} {interval}: error {e
