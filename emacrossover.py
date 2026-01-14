#!/usr/bin/env python3
"""
EMA Crossover Alert System for BTCUSDT
- Checks 5min candle close for 30/60 EMA crossover
- Confirms with 15min and 30min higher timeframe alignment
- Sends Telegram alerts for LONG/SHORT signals
"""

import os
import requests
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables


load_dotenv()

BINANCE_API_KEY = os.getenv("API_KEY")
BINANCE_API_SECRET = os.getenv("API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

SYMBOL = "BTCUSDT"
EMA_FAST = 30
EMA_SLOW = 60


def fetch_klines(symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
    """Fetch klines from Binance API."""
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    
    df["close"] = df["close"].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    
    return df


def calculate_ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    """Calculate EMA for given period."""
    return df[column].ewm(span=period, adjust=False).mean()


def get_ema_values(symbol: str, interval: str) -> dict:
    """Get current EMA values for a timeframe."""
    df = fetch_klines(symbol, interval, limit=EMA_SLOW + 10)
    
    ema_fast = calculate_ema(df, EMA_FAST)
    ema_slow = calculate_ema(df, EMA_SLOW)
    
    # Use second to last candle (last closed candle)
    return {
        "ema_fast": ema_fast.iloc[-2],
        "ema_slow": ema_slow.iloc[-2],
        "ema_fast_prev": ema_fast.iloc[-3],
        "ema_slow_prev": ema_slow.iloc[-3],
        "close_time": df["close_time"].iloc[-2],
        "close_price": df["close"].iloc[-2]
    }


def check_ema_crossover(current: dict) -> str | None:
    """
    Check for EMA crossover on the latest closed candle.
    Returns 'LONG', 'SHORT', or None.
    """
    fast_now = current["ema_fast"]
    slow_now = current["ema_slow"]
    fast_prev = current["ema_fast_prev"]
    slow_prev = current["ema_slow_prev"]
    
    # Bullish crossover: fast crosses above slow
    if fast_prev <= slow_prev and fast_now > slow_now:
        return "LONG"
    
    # Bearish crossover: fast crosses below slow
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "SHORT"
    
    return None


def check_htf_alignment(symbol: str, direction: str) -> dict:
    """
    Check if higher timeframes (15m, 30m) are aligned with the signal.
    For LONG: fast EMA should be above slow EMA
    For SHORT: fast EMA should be below slow EMA
    """
    htf_15m = get_ema_values(symbol, "15m")
    htf_30m = get_ema_values(symbol, "30m")
    
    if direction == "LONG":
        aligned_15m = htf_15m["ema_fast"] > htf_15m["ema_slow"]
        aligned_30m = htf_30m["ema_fast"] > htf_30m["ema_slow"]
    else:  # SHORT
        aligned_15m = htf_15m["ema_fast"] < htf_15m["ema_slow"]
        aligned_30m = htf_30m["ema_fast"] < htf_30m["ema_slow"]
    
    return {
        "15m_aligned": aligned_15m,
        "30m_aligned": aligned_30m,
        "15m_ema_fast": htf_15m["ema_fast"],
        "15m_ema_slow": htf_15m["ema_slow"],
        "30m_ema_fast": htf_30m["ema_fast"],
        "30m_ema_slow": htf_30m["ema_slow"]
    }


def send_telegram_alert(message: str) -> bool:
    """Send alert to Telegram channel."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"Telegram alert sent successfully")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Failed to send Telegram alert: {e}")
        return False


def format_alert_message(direction: str, data_5m: dict, htf_data: dict) -> str:
    """Format the alert message for Telegram."""
    emoji = "🟢" if direction == "LONG" else "🔴"
    
    message = f"""
{emoji} <b>EMA CROSSOVER ALERT - {direction}</b> {emoji}

<b>Symbol:</b> {SYMBOL}
<b>Signal Time:</b> {data_5m['close_time'].strftime('%Y-%m-%d %H:%M:%S')} UTC
<b>Close Price:</b> ${data_5m['close_price']:,.2f}

<b>5m EMA Status:</b>
• EMA{EMA_FAST}: {data_5m['ema_fast']:,.2f}
• EMA{EMA_SLOW}: {data_5m['ema_slow']:,.2f}

<b>15m EMA Alignment:</b> {'✅' if htf_data['15m_aligned'] else '❌'}
• EMA{EMA_FAST}: {htf_data['15m_ema_fast']:,.2f}
• EMA{EMA_SLOW}: {htf_data['15m_ema_slow']:,.2f}

<b>30m EMA Alignment:</b> {'✅' if htf_data['30m_aligned'] else '❌'}
• EMA{EMA_FAST}: {htf_data['30m_ema_fast']:,.2f}
• EMA{EMA_SLOW}: {htf_data['30m_ema_slow']:,.2f}

<i>All timeframes aligned - Signal confirmed!</i>
"""
    return message


def main():
    """Main function to check for signals and send alerts."""
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Checking EMA crossover for {SYMBOL}...")
    
    try:
        # Get 5m EMA data
        data_5m = get_ema_values(SYMBOL, "5m")
        
        # Check for crossover on 5m
        crossover = check_ema_crossover(data_5m)
        
        if crossover is None:
            message = "<p>No crossover detected on 5m timeframe.</p>"
            send_telegram_alert(message)
            return
        
        message = f"<p>{crossover} crossover detected on 5m! Checking HTF alignment.</p>"
        send_telegram_alert(message)
        
        # Check higher timeframe alignment
        htf_data = check_htf_alignment(SYMBOL, crossover)
        
        if not htf_data["15m_aligned"]:
            message = f"<p>15m not aligned for {crossover} - skipping signal</p>"
            send_telegram_alert(message)
            return
        
        if not htf_data["30m_aligned"]:
            message = f"<p>30m not aligned for {crossover} - skipping signal</p>"
            send_telegram_alert(message)
            return
        
        # All conditions met - send alert
        print(f"All conditions met! Sending {crossover} alert...")
        message = format_alert_message(crossover, data_5m, htf_data)
        send_telegram_alert(message)
        
    except requests.exceptions.RequestException as e:
        print(f"API error: {e}")
    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()