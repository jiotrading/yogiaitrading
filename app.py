from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import yfinance as yf
import requests
import os
import asyncio
from datetime import datetime, timezone

app = FastAPI(title="Jio AI-Trading Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ASSET_UNIVERSE = {
    "Solana (SOL)": "SOL-USD",
    "Bitcoin (BTC)": "BTC-USD",
    "XRP": "XRP-USD",
    "Ethereum (ETH)": "ETH-USD",
    "Shiba Inu (SHIB)": "SHIB-USD",
    "Nifty 50": "^NSEI",
    "Bank Nifty": "^NSEBANK"
}

broadcast_history = {}
latest_scan_cache = {}

def send_telegram_alert(message: str):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

def calculate_institutional_signal(df_5m):
    if len(df_5m) < 35:
        return 0, "INSUFFICIENT_DATA", 50, 0, False, 0
    
    last_candle_time = df_5m.index[-2]
    now_utc = datetime.now(timezone.utc)
    if last_candle_time.tzinfo is None:
        last_candle_time = last_candle_time.tz_localize('UTC')
        
    time_diff_minutes = (now_utc - last_candle_time).total_seconds() / 60.0
    is_fresh = time_diff_minutes <= 12.0
    
    c5 = pd.Series(df_5m['Close'].values.flatten(), index=df_5m.index)
    h5 = pd.Series(df_5m['High'].values.flatten(), index=df_5m.index)
    l5 = pd.Series(df_5m['Low'].values.flatten(), index=df_5m.index)
    v5 = pd.Series(df_5m['Volume'].values.flatten(), index=df_5m.index)
    
    delta = c5.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean() + 1e-10
    rsi = 100 - (100 / (1 + (gain / loss)))
    cur_rsi = float(rsi.iloc[-2])
    
    ema9_val = float(c5.ewm(span=9, adjust=False).mean().iloc[-2])
    ema21_val = float(c5.ewm(span=21, adjust=False).mean().iloc[-2])
    
    tr = pd.DataFrame([h5 - l5, abs(h5 - c5.shift(1)), abs(l5 - c5.shift(1))]).max()
    atr = float(tr.rolling(14).mean().iloc[-2])
    
    vol_avg = float(v5.rolling(20).mean().iloc[-2])
    cur_vol = float(v5.iloc[-2])
    is_high_volume = cur_vol > (vol_avg * 1.05)
    
    signal = 0
    reason = "Scanning Trend..."
    
    if ema9_val > ema21_val:
        if cur_rsi > 68:
            reason = "🛑 BUY BLOCKED: Overbought Top Zone (RSI > 68)"
        elif cur_rsi < 42:
            reason = "⚠️ BUY BLOCKED: Low Momentum"
        elif not is_high_volume:
            reason = "⚠️ BUY BLOCKED: Low Volume Fakeout"
        else:
            signal = 1
            reason = "🚀 HIGH ACCURACY BUY SIGNAL!"
            
    elif ema9_val < ema21_val:
        if cur_rsi < 32:
            reason = "🛑 SELL BLOCKED: Oversold Bottom Zone (RSI < 32)"
        elif cur_rsi > 58:
            reason = "⚠️ SELL BLOCKED: Bearish Momentum Fading"
        elif not is_high_volume:
            reason = "⚠️ SELL BLOCKED: Low Volume Drift"
        else:
            signal = -1
            reason = "💥 HIGH ACCURACY SELL SIGNAL!"
            
    return signal, reason, cur_rsi, atr, is_fresh, time_diff_minutes

async def background_radar_scanner():
    while True:
        for name, symbol in ASSET_UNIVERSE.items():
            try:
                df_raw = yf.download(tickers=symbol, period="2d", interval="5m", progress=False)
                if df_raw is not None and not df_raw.empty and len(df_raw) > 35:
                    if isinstance(df_raw.columns, pd.MultiIndex):
                        df_raw.columns = df_raw.columns.get_level_values(0)
                        
                    sig, reason, rsi, atr, is_fresh, age = calculate_institutional_signal(df_raw)
                    c_price = float(df_raw['Close'].values.flatten()[-1])
                    p_fmt = ",.8f" if symbol == "SHIB-USD" else ",.2f"
                    
                    sl = c_price - (2.2 * atr) if sig == 1 else (c_price + (2.2 * atr) if sig == -1 else 0)
                    tp = c_price + (4.4 * atr) if sig == 1 else (c_price - (4.4 * atr) if sig == -1 else 0)
                    
                    latest_scan_cache[symbol] = {
                        "asset": name,
                        "symbol": symbol,
                        "price": f"{c_price:{p_fmt}}",
                        "raw_price": c_price,
                        "rsi": round(rsi, 1),
                        "signal": sig,
                        "reason": reason,
                        "is_fresh": is_fresh,
                        "candle_age_min": round(age, 1),
                        "sl": f"{sl:{p_fmt}}" if sl != 0 else "-",
                        "tp": f"{tp:{p_fmt}}" if tp != 0 else "-"
                    }
                    
                    if is_fresh and sig != 0:
                        action_type = "BUY" if sig == 1 else "SELL"
                        candle_time_str = str(df_raw.index[-2])
                        unique_key = f"{symbol}{action_type}{candle_time_str}"
                        
                        if broadcast_history.get(symbol) != unique_key:
                            icon = "🚀" if sig == 1 else "💥"
                            msg = (
                                f"{icon} JIO SUPER AI-PRECISION {action_type} ALERT\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"📊 Asset: {name}\n"
                                f"🟩 Spot Entry: {c_price:{p_fmt}}\n"
                                f"🛑 Dynamic SL: {sl:{p_fmt}}\n"
                                f"🎯 Target (1:2.0): {tp:{p_fmt}}\n"
                                f"📈 RSI Value: {rsi:.1f}\n"
                                f"⏰ Generated: Just now ({age:.1f}m ago)\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"🤖 FastAPI Background Radar Engine"
                            )
                            send_telegram_alert(msg)
                            broadcast_history[symbol] = unique_key
            except Exception:
                pass
        await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_radar_scanner())

@app.get("/")
def home():
    return {"status": "online", "message": "Jio AI-Trading FastAPI Engine Running"}

@app.get("/api/signals")
def get_signals():
    return {"success": True, "data": list(latest_scan_cache.values())}
