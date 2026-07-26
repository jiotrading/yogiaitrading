from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import asyncio
import json
from datetime import datetime

app = FastAPI(title="Jio AI Ultra Engine V11.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(message):
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
    return df

ASSETS = [
    {"symbol": "SOL-USD", "name": "Solana"},
    {"symbol": "BTC-USD", "name": "Bitcoin"},
    {"symbol": "ETH-USD", "name": "Ethereum"},
    {"symbol": "XRP-USD", "name": "XRP"},
    {"symbol": "^NSEI", "name": "Nifty 50"},
    {"symbol": "^NSEBANK", "name": "Bank Nifty"},
]

@app.get("/api/signals")
def get_signals():
    results = []
    for asset in ASSETS:
        try:
            df = yf.download(asset["symbol"], period="8d", interval="5m", progress=False)
            if len(df) < 100:
                continue
            df = calculate_indicators(df)
            latest = df.iloc[-1]
            
            score = 0
            if latest['EMA8'] > latest['EMA13'] > latest['EMA21']:
                score += 35
            if latest['MACD'] > latest['MACD_Signal']:
                score += 25
            if 45 < latest['RSI'] < 68:
                score += 20
            if latest['Volume'] > latest['Volume'].rolling(20).mean() * 1.4:
                score += 15
            
            confidence = max(40, min(95, score))
            
            if confidence >= 70:
                price = float(latest['Close'])
                atr = float(latest['ATR']) if 'ATR' in df.columns else 50
                
                is_buy = latest['EMA8'] > latest['EMA13']
                
                signal_data = {
                    "asset": asset["name"],
                    "symbol": asset["symbol"],
                    "signal": "BUY" if is_buy else "SELL",
                    "price": round(price, 4),
                    "confidence": int(confidence),
                    "sl": round(price - (2.8 * atr) if is_buy else price + (2.8 * atr), 4),
                    "tp": round(price + (6.5 * atr) if is_buy else price - (6.5 * atr), 4),
                    "time": datetime.now().strftime("%H:%M"),
                    "status": "LIVE"
                }
                results.append(signal_data)
                
                # Telegram
                msg = f"🚨 <b>{asset['name']}</b> → <b>{signal_data['signal']}</b>\nPrice: {signal_data['price']}\nConfidence: {signal_data['confidence']}%\nSL: {signal_data['sl']} | TP: {signal_data['tp']}"
                send_telegram(msg)
                
        except:
            continue
    
    return {"success": True, "data": results, "scanning": True}

@app.get("/")
def root():
    return {"status": "Jio AI Ultra Engine V11.0 Active", "scanner": "24/7"}

print("✅ V11.0 Loaded - Ready for Signals")
