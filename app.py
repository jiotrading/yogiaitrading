from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import json
import asyncio
from datetime import datetime

app = FastAPI(title="Jio AI Ultra Engine V11.0 - Complete Power")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

HISTORY_FILE = "trading_history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(entry):
    history = load_history()
    history.append(entry)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history[-20000:], f)

def send_telegram(message: str):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                          json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        except:
            pass

def calculate_indicators(df):
    df = df.copy()
    for span in [8, 13, 21, 50, 100, 200]:
        df[f'EMA{span}'] = df['Close'].ewm(span=span, adjust=False).mean()
    
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean() + 1e-10
    df['RSI'] = 100 - (100 / (1 + gain / loss))
    
    df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
    df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
    
    low14 = df['Low'].rolling(14).min()
    high14 = df['High'].rolling(14).max()
    df['Stoch'] = 100 * (df['Close'] - low14) / (high14 - low14)
    
    tr = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift()), abs(df['Low']-df['Close'].shift())], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    df['Vol_SMA'] = df['Volume'].rolling(20).mean()
    return df

def generate_signal(asset):
    try:
        df = yf.download(asset["symbol"], period="12d", interval="5m", progress=False)
        if len(df) < 150: return None
            
        df = calculate_indicators(df)
        latest = df.iloc[-1]
        
        score = 0
        if latest['EMA8'] > latest['EMA13'] > latest['EMA21'] > latest['EMA50']:
            score += 40
        if latest['MACD'] > latest['MACD_Signal']:
            score += 25
        if 45 < latest['RSI'] < 68:
            score += 18
        if latest['Stoch'] < 35:
            score += 12
        if latest['Volume'] > latest['Vol_SMA'] * 1.55:
            score += 20
        
        confidence = max(35, min(98, score))
        
        if confidence < 73: return None
        
        price = float(latest['Close'])
        atr = float(latest['ATR'])
        is_buy = latest['EMA8'] > latest['EMA13']
        
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "asset": asset["name"],
            "signal": "BUY" if is_buy else "SELL",
            "price": round(price, 4),
            "confidence": int(confidence),
            "sl": round(price - (2.8 * atr) if is_buy else price + (2.8 * atr), 4),
            "tp": round(price + (6.8 * atr) if is_buy else price - (6.8 * atr), 4),
            "reason": "Multi-Indicator Strong Confluence",
            "grade": "ELITE" if confidence > 80 else "HIGH"
        }
        
        save_history(entry)
        
        # Beautiful Telegram Alert
        if confidence >= 75:
            msg = f"""
🚨 <b>JIO AI ULTRA V11.0</b> 🚨
Asset: <b>{entry['asset']}</b>
Signal: <b>{entry['signal']}</b> | Grade: <b>{entry['grade']}</b>
Price: <b>{entry['price']}</b>
Confidence: <b>{entry['confidence']}%</b>
Stop Loss: {entry['sl']}
Target: {entry['tp']}
Reason: {entry['reason']}
Time: {entry['timestamp']}
            """
            send_telegram(msg)
        
        return entry
    except:
        return None

ASSETS = [
    {"symbol": "BTC-USD", "name": "Bitcoin"},
    {"symbol": "ETH-USD", "name": "Ethereum"},
    {"symbol": "SOL-USD", "name": "Solana"},
    {"symbol": "^NSEI", "name": "Nifty 50"},
    {"symbol": "^NSEBANK", "name": "Bank Nifty"},
]

@app.get("/")
def root():
    return {"status": "Jio AI Ultra Engine V11.0 - Fully Loaded ✅", "success": True}

@app.get("/api/signals")
def get_signals():
    results = []
    for asset in ASSETS:
        res = generate_signal(asset)
        if res:
            results.append(res)
    return {"success": True, "count": len(results), "data": results}

@app.get("/api/history")
def get_history(limit: int = 100):
    history = load_history()
    return {"success": True, "total": len(history), "data": history[-limit:]}

async def background_scanner():
    while True:
        await asyncio.sleep(180)

@app.on_event("startup")
async def startup():
    asyncio.create_task(background_scanner())
