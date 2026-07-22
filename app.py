from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import asyncio
from datetime import datetime, timezone

app = FastAPI(title="Jio AI Ultra-Institutional Trading Engine V3.0")

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

latest_scan_cache = {}
broadcast_history = {}

def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print("Telegram Alert Error:", e)

def calculate_advanced_indicators(df):
    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()

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

    # ADX (14) - Trend Strength
    up_move = df['High'] - df['High'].shift(1)
    down_move = df['Low'].shift(1) - df['Low']
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    tr_smooth = tr.rolling(window=14).sum()
    plus_di = 100 * (pd.Series(plus_dm).rolling(window=14).sum() / (tr_smooth + 1e-10))
    minus_di = 100 * (pd.Series(minus_dm).rolling(window=14).sum() / (tr_smooth + 1e-10))
    dx = 100 * (np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10))
    df['ADX'] = dx.rolling(window=14).mean()

    # Volume Moving Average
    df['Vol_SMA'] = df['Volume'].rolling(window=20).mean()

    return df

def process_institutional_signal(symbol: str, name: str, is_crypto: bool):
    try:
        # Fetch Multi-Timeframe Data (5m, 15m, 1h)
        d5 = yf.download(symbol, period="3d", interval="5m", progress=False)
        d15 = yf.download(symbol, period="5d", interval="15m", progress=False)
        d1h = yf.download(symbol, period="10d", interval="1h", progress=False)

        if d5.empty or len(d5) < 35 or d15.empty or d1h.empty:
            return None

        # Clean MultiIndex
        for d in [d5, d15, d1h]:
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)

        df5 = calculate_advanced_indicators(d5)
        df15 = calculate_advanced_indicators(d15)
        df1h = calculate_advanced_indicators(d1h)

        l5, p5 = df5.iloc[-1], df5.iloc[-2]
        l15 = df15.iloc[-1]
        l1h = df1h.iloc[-1]

        c_price = float(l5['Close'])
        rsi = float(l5['RSI'])
        atr = float(l5['ATR'])
        adx = float(l5['ADX'])
        vol = float(l5['Volume'])
        vol_avg = float(l5['Vol_SMA'])

        # Timeframe Confluences
        macro_bullish = l1h['EMA9'] > l1h['EMA21']
        macro_bearish = l1h['EMA9'] < l1h['EMA21']

        mid_bullish = l15['EMA9'] > l15['EMA21']
        mid_bearish = l15['EMA9'] < l15['EMA21']

        vol_spike = vol >= (1.30 * vol_avg)
        is_trending = adx > 20.0  # ADX Filter for Chop protection

        signal = 0
        reason = "SCANNING: Range Bound / Waiting for Institutional Liquidity"

        # Signal Triggers
        buy_cross = (p5['EMA9'] <= p5['EMA21']) and (l5['EMA9'] > l5['EMA21'])
        sell_cross = (p5['EMA9'] >= p5['EMA21']) and (l5['EMA9'] < l5['EMA21'])

        if not is_trending:
            reason = "🛑 NO TRADE: Low ADX (SideMarket / Consolidation Zone)"
        elif buy_cross:
            if macro_bullish and mid_bullish and rsi < 68 and vol_spike:
                signal = 1
                reason = "🚀 ULTRA BUY: 1H + 15M Macro Confluence + Vol Spike!"
            else:
                reason = "⚠️ BUY BLOCKED: High Timeframe Resistance or Low Volume"
        elif sell_cross:
            if macro_bearish and mid_bearish and rsi > 32 and vol_spike:
                signal = -1
                reason = "💥 ULTRA SELL: 1H + 15M Bearish Order Block + Institutional Vol!"
            else:
                reason = "⚠️ SELL BLOCKED: Higher Timeframe Support Detected"

        # Adaptive SL & TP Multipliers
        sl_mult = 2.8 if is_crypto else 2.2
        tp_mult = 5.6 if is_crypto else 4.4

        p_fmt = ",.8f" if symbol == "SHIB-USD" else ",.2f"
        sl = c_price - (sl_mult * atr) if signal == 1 else (c_price + (sl_mult * atr) if signal == -1 else c_price - atr)
        tp = c_price + (tp_mult * atr) if signal == 1 else (c_price - (tp_mult * atr) if signal == -1 else c_price + atr)

        res_data = {
            "symbol": symbol,
            "asset": name,
            "price": f"{c_price:{p_fmt}}",
            "raw_price": c_price,
            "signal": signal,
            "rsi": round(rsi, 1),
            "adx": round(adx, 1),
            "reason": reason,
            "sl": f"{sl:{p_fmt}}",
            "tp": f"{tp:{p_fmt}}"
        }

        latest_scan_cache[symbol] = res_data
        return res_data

    except Exception as e:
        print(f"Error processing {symbol}: {e}")
        return None

@app.get("/")
def root():
    return {"status": "Online", "engine": "Jio AI Institutional V3 Engine"}

@app.get("/api/signals")
def get_signals():
    results = []
    for item in ASSETS:
        res = process_institutional_signal(item["symbol"], item["name"], is_crypto=(item["type"] == "crypto"))
        if res:
            results.append(res)
    return {"success": True, "count": len(results), "data": results}

async def background_radar_scanner():
    while True:
        for item in ASSETS:
            res = process_institutional_signal(item["symbol"], item["name"], is_crypto=(item["type"] == "crypto"))
            if res and res["signal"] != 0:
                sig_type = "BUY" if res["signal"] == 1 else "SELL"
                unique_key = f"{res['symbol']}{sig_type}{res['price']}"
                
                if broadcast_history.get(res['symbol']) != unique_key:
                    icon = "🚀" if res["signal"] == 1 else "💥"
                    msg = (
                        f"{icon} <b>JIO AI ULTRA-ACCURATE {sig_type} SIREN</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📊 <b>Asset:</b> {res['asset']}\n"
                        f"🟩 <b>Entry Price:</b> ${res['price']}\n"
                        f"🛑 <b>Adaptive SL:</b> ${res['sl']}\n"
                        f"🎯 <b>Target (1:2.0+):</b> ${res['tp']}\n"
                        f"📈 <b>ADX Trend Power:</b> {res['adx']}\n"
                        f"🔥 <b>Reason:</b> {res['reason']}\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🤖 <i>Institutional SMC Radar V3 Engine</i>"
                    )
                    send_telegram_alert(msg)
                    broadcast_history[res['symbol']] = unique_key
        await asyncio.sleep(20)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_radar_scanner())
