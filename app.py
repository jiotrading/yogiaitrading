import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Jio Institutional AI Trading Engine V4.2")

# CORS Setup for Vercel Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

# Alert cooldown to prevent Telegram spamming
last_alert_time = {}
ALERT_COOLDOWN = 1800  # 30 Minutes Cooldown

def send_telegram_alert(symbol, signal_type, price, rsi, ema_status, sl, tp1, tp2):
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        return
    
    current_time = time.time()
    # Check cooldown per symbol
    if symbol in last_alert_time:
        if current_time - last_alert_time[symbol] < ALERT_COOLDOWN:
            print(f"Skipping spam alert for {symbol}. Cooldown active.")
            return

    # Update timestamp
    last_alert_time[symbol] = current_time

    # Decimal formatting: 8 decimals for Micro-price tokens like SHIB
    p_str = f"{price:.8f}" if "SHIB" in symbol else f"{price:.4f}"
    sl_str = f"{sl:.8f}" if "SHIB" in symbol else f"{sl:.4f}"
    tp1_str = f"{tp1:.8f}" if "SHIB" in symbol else f"{tp1:.4f}"
    tp2_str = f"{tp2:.8f}" if "SHIB" in symbol else f"{tp2:.4f}"
    
    emoji = "🚀 BUY SIGNAL" if signal_type == "BUY" else "🔻 SELL SIGNAL"
    message = f"""
{emoji} | *Jio AI Engine V4.2*
----------------------------------
🎯 *Asset:* {symbol}
📊 *Entry Price:* ${p_str}
📈 *RSI (14):* {rsi:.2f}
📉 *Trend Confirmation:* {ema_status}

🛑 *Stop Loss (ATR):* ${sl_str}
🎯 *Target 1:* ${tp1_str}
🚀 *Target 2:* ${tp2_str}
----------------------------------
⚡ Institutional Signal
"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except Exception as e:
        print(f"Telegram Error: {e}")

def calculate_indicators(df):
    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(14).mean()
    
    df['Vol_Avg'] = df['Volume'].rolling(20).mean()
    return df

def analyze_asset(ticker):
    try:
        time.sleep(0.5) 
        df = yf.download(ticker, period="7d", interval="1h", progress=False, threads=False)
        
        if df.empty or len(df) < 50:
            return {"symbol": ticker, "status": "Insufficient Data"}
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = calculate_indicators(df)
        curr = df.iloc[-1]
        
        close = float(curr['Close'])
        rsi = float(curr['RSI'])
        macd = float(curr['MACD'])
        signal_line = float(curr['Signal_Line'])
        ema20 = float(curr['EMA_20'])
        ema50 = float(curr['EMA_50'])
        ema200 = float(curr['EMA_200'])
        atr = float(curr['ATR'])
        
        signal = "NEUTRAL"
        ema_status = "RANGING"
        
        if close > ema200 and ema20 > ema50:
            ema_status = "BULLISH TREND"
            if rsi > 50 and macd > signal_line:
                signal = "BUY"
                sl = close - (1.5 * atr)
                tp1 = close + (2.0 * atr)
                tp2 = close + (3.5 * atr)
                send_telegram_alert(ticker, "BUY", close, rsi, ema_status, sl, tp1, tp2)
                
        elif close < ema200 and ema20 < ema50:
            ema_status = "BEARISH TREND"
            if rsi < 50 and macd < signal_line:
                signal = "SELL"
                sl = close + (1.5 * atr)
                tp1 = close - (2.0 * atr)
                tp2 = close - (3.5 * atr)
                send_telegram_alert(ticker, "SELL", close, rsi, ema_status, sl, tp1, tp2)
                
        return {
            "symbol": ticker,
            "price": round(close, 8) if "SHIB" in ticker else round(close, 4),
            "signal": signal,
            "trend": ema_status,
            "rsi": round(rsi, 2)
        }
    except Exception as e:
        return {"symbol": ticker, "status": f"Error: {str(e)}"}

@app.get("/")
def root():
    return {"status": "Online", "engine": "Jio Institutional AI Engine V4.2"}

@app.get("/api/signals")
def get_signals():
    tickers = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "SHIB-USD", "^NSEI"]
    results = []
    for t in tickers:
        results.append(analyze_asset(t))
    return results
