import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from concurrent.futures import ThreadPoolExecutor

app = FastAPI(title="Jio Institutional AI Trading Engine V4.0")

# CORS Setup for Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Telegram Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

def send_telegram_alert(symbol, signal_type, price, rsi, ema_status, sl, tp1, tp2):
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("Telegram Token not set.")
        return
    
    emoji = "🚀 BUY SIGNAL" if signal_type == "BUY" else "🔻 SELL SIGNAL"
    message = f"""
{emoji} | *Jio AI Engine V4.0*
----------------------------------
🎯 *Asset:* {symbol}
📊 *Entry Price:* ${price:.4f}
📈 *RSI (14):* {rsi:.2f}
📉 *Trend Confirmation:* {ema_status}

🛑 *Stop Loss (ATR Based):* ${sl:.4f}
🎯 *Target 1 (1:1.5):* ${tp1:.4f}
🚀 *Target 2 (1:3.0):* ${tp2:.4f}
----------------------------------
⚡ High-Probability Institutional Signal
"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")

# Quantitative Indicator Logic
def calculate_indicators(df):
    # 1. EMAs
    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    # 2. RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 3. MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # 4. ATR (Volatility Stop Loss)
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(14).mean()
    
    # 5. Volume Average
    df['Vol_Avg'] = df['Volume'].rolling(20).mean()
    return df

# Advanced Signal Logic Rules
def analyze_asset(ticker):
    try:
        # Fetch 1-hour candle data
        df = yf.download(ticker, period="7d", interval="1h", progress=False)
        if df.empty or len(df) < 50:
            return {"symbol": ticker, "status": "Insufficient Data"}
            
        df = calculate_indicators(df)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        close = float(curr['Close'])
        rsi = float(curr['RSI'])
        macd = float(curr['MACD'])
        signal_line = float(curr['Signal_Line'])
        ema20 = float(curr['EMA_20'])
        ema50 = float(curr['EMA_50'])
        ema200 = float(curr['EMA_200'])
        vol = float(curr['Volume'])
        vol_avg = float(curr['Vol_Avg'])
        atr = float(curr['ATR'])
        
        signal = "NEUTRAL"
        ema_status = "RANGING"
        
        # Bullish Institutional Rule Set
        # Rule 1: Price > 200 EMA (Uptrend)
        # Rule 2: EMA 20 > EMA 50
        # Rule 3: RSI between 52 and 68 (Strong momentum without overbought)
        # Rule 4: Volume > 1.3x Vol_Avg (Breakout confirmation)
        # Rule 5: MACD Crossover
        if close > ema200 and ema20 > ema50:
            ema_status = "BULLISH TREND"
            if rsi > 52 and rsi < 68 and macd > signal_line and vol > (1.2 * vol_avg):
                signal = "BUY"
                sl = close - (1.5 * atr)
                tp1 = close + (2.2 * atr)
                tp2 = close + (4.0 * atr)
                send_telegram_alert(ticker, "BUY", close, rsi, ema_status, sl, tp1, tp2)
                
        # Bearish Institutional Rule Set
        elif close < ema200 and ema20 < ema50:
            ema_status = "BEARISH TREND"
            if rsi < 48 and rsi > 32 and macd < signal_line and vol > (1.2 * vol_avg):
                signal = "SELL"
                sl = close + (1.5 * atr)
                tp1 = close - (2.2 * atr)
                tp2 = close - (4.0 * atr)
                send_telegram_alert(ticker, "SELL", close, rsi, ema_status, sl, tp1, tp2)
                
        return {
            "symbol": ticker,
            "price": round(close, 4),
            "signal": signal,
            "trend": ema_status,
            "rsi": round(rsi, 2),
            "volume_spike": "YES" if vol > (1.2 * vol_avg) else "NORMAL"
        }
    except Exception as e:
        return {"symbol": ticker, "status": f"Error: {str(e)}"}

@app.get("/")
def root():
    return {"status": "Online", "engine": "Jio Institutional AI Engine V4.0"}

@app.get("/api/signals")
def get_signals():
    tickers = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "SHIB-USD", "^NSEI"]
    results = []
    
    # Parallel processing using Multi-threading to avoid stuck loops
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(analyze_asset, tickers))
        
    return {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "signals": results}
