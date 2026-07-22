from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import asyncio

app = FastAPI(title="Jio AI Ultra Engine V3.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ASSETS = [
    {"symbol": "SOL-USD", "name": "Solana (SOL)", "type": "crypto"},
    {"symbol": "BTC-USD", "name": "Bitcoin (BTC)", "type": "crypto"},
    {"symbol": "ETH-USD", "name": "Ethereum (ETH)", "type": "crypto"},
    {"symbol": "XRP-USD", "name": "XRP", "type": "crypto"},
    {"symbol": "SHIB-USD", "name": "Shiba Inu (SHIB)", "type": "crypto"},
    {"symbol": "^NSEI", "name": "Nifty 50", "type": "index"},
    {"symbol": "^NSEBANK", "name": "Bank Nifty", "type": "index"},
]

def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print("Telegram Alert Error:", e)

def calculate_indicators(df):
    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()

    # RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean() + 1e-10
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # ATR (14)
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=14).mean()

    # Vol SMA
    df['Vol_SMA'] = df['Volume'].rolling(window=20).mean()

    return df

def process_asset(symbol: str, name: str, is_crypto: bool):
    try:
        data = yf.download(symbol, period="5d", interval="5m", progress=False)
        if data.empty or len(data) < 30:
            return None

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        df = calculate_indicators(data)
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        c_price = float(latest['Close'])
        rsi = float(latest['RSI'])
        atr = float(latest['ATR'])
        vol = float(latest['Volume'])
        vol_avg = float(latest['Vol_SMA'])

        # Crossovers & Trend Logic
        buy_cross = (prev['EMA9'] <= prev['EMA21']) and (latest['EMA9'] > latest['EMA21'])
        sell_cross = (prev['EMA9'] >= prev['EMA21']) and (latest['EMA9'] < latest['EMA21'])

        is_bullish_trend = latest['EMA9'] > latest['EMA50']
        is_bearish_trend = latest['EMA9'] < latest['EMA50']
        vol_confirmed = vol >= (1.15 * vol_avg)

        signal = 0
        reason = "SCANNING: Range Bound / Waiting for Institutional Volume"

        if buy_cross:
            if is_bullish_trend and rsi < 68 and vol_confirmed:
                signal = 1
                reason = "🟢 STRONG BUY: EMA Crossover + Trend Confluence + Volume"
            else:
                reason = "⚠️ BUY BLOCKED: High Resistance or Low Volume"
        elif sell_cross:
            if is_bearish_trend and rsi > 32 and vol_confirmed:
                signal = -1
                reason = "🔴 STRONG SELL: Bearish Trend + Institutional Volume"
            else:
                reason = "⚠️ SELL BLOCKED: Bearish Momentum Fading"

        sl_mult = 2.8 if is_crypto else 2.0
        tp_mult = 5.2 if is_crypto else 4.0

        sl = c_price - (sl_mult * atr) if signal == 1 else (c_price + (sl_mult * atr) if signal == -1 else c_price - atr)
        tp = c_price + (tp_mult * atr) if signal == 1 else (c_price - (tp_mult * atr) if signal == -1 else c_price + atr)

        p_fmt = ",.8f" if symbol == "SHIB-USD" else ",.2f"

        return {
            "symbol": symbol,
            "asset": name,
            "price": f"{c_price:{p_fmt}}",
            "signal": signal,
            "rsi": round(rsi, 1),
            "reason": reason,
            "sl": f"{sl:{p_fmt}}",
            "tp": f"{tp:{p_fmt}}"
        }
    except Exception as e:
        print(f"Error {symbol}: {e}")
        return None

@app.get("/")
def root():
    return {"status": "Online", "engine": "Jio AI Engine V3.1"}

@app.get("/api/signals")
def get_signals():
    results = []
    for item in ASSETS:
        res = process_asset(item["symbol"], item["name"], is_crypto=(item["type"] == "crypto"))
        if res:
            results.append(res)
    return {"success": True, "count": len(results), "data": results}

async def background_radar():
    broadcasted = {}
    while True:
        for item in ASSETS:
            res = process_asset(item["symbol"], item["name"], is_crypto=(item["type"] == "crypto"))
            if res and res["signal"] != 0:
                key = f"{res['symbol']}{res['signal']}{res['price']}"
                if broadcasted.get(res['symbol']) != key:
                    sig_str = "BUY" if res["signal"] == 1 else "SELL"
                    icon = "🟢" if res["signal"] == 1 else "🔴"
                    msg = (
                        f"🚨 <b>JIO AI SIREN ALERT ({sig_str})</b> 🚨\n\n"
                        f"Asset: {res['asset']}\n"
                        f"Price: ${res['price']}\n"
                        f"Stop Loss: ${res['sl']}\n"
                        f"Target: ${res['tp']}\n"
                        f"Reason: {res['reason']}"
                    )
                    send_telegram_alert(msg)
                    broadcasted[res['symbol']] = key
        await asyncio.sleep(25)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_radar())
