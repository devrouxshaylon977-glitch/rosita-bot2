import os, requests, threading, time, asyncio
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY")

app = Flask(__name__)

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
            params={"symbol": symbol, "interval
