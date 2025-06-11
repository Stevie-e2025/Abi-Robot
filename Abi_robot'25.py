import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

symbol = "GOLD"
magic_number = 10001

BUFFER_PIPS = 20 * 0.0001  # 20 pip buffer
RSI_BUY_THRESHOLD = 40
RSI_SELL_THRESHOLD = 60

def connect():
    if not mt5.initialize():
        raise Exception("MT5 initialization failed")
    print("✅ Connected to MT5")

def shutdown():
    mt5.shutdown()

def get_data(symbol, timeframe, bars=100):
    tf_map = {
        '1d': mt5.TIMEFRAME_D1,
        '4h': mt5.TIMEFRAME_H4,
        '1h': mt5.TIMEFRAME_H1
    }

    if timeframe not in tf_map:
        print(f"Invalid timeframe: {timeframe}")
        return pd.DataFrame()

    if not mt5.symbol_select(symbol, True):
        print(f"Could not select symbol: {symbol}")
        return pd.DataFrame()

    rates = mt5.copy_rates_from_pos(symbol, tf_map[timeframe], 0, bars)

    if rates is None or len(rates) == 0:
        print(f"No rates returned for {symbol} on {timeframe}")
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def find_support_resistance(df):
    levels = []
    for i in range(2, len(df) - 2):
        if df['high'][i] > df['high'][i-1] and df['high'][i] > df['high'][i+1]:
            levels.append(('resistance', df['high'][i]))
        if df['low'][i] < df['low'][i-1] and df['low'][i] < df['low'][i+1]:
            levels.append(('support', df['low'][i]))
    return levels

def apply_fibonacci(df):
    high = df['high'].max()
    low = df['low'].min()
    diff = high - low
    return {
        "0.0%": high,
        "23.6%": high - 0.236 * diff,
        "38.2%": high - 0.382 * diff,
        "50.0%": high - 0.5 * diff,
        "61.8%": high - 0.618 * diff,
        "100.0%": low
    }

def detect_engulfing(df):
    if len(df) < 2:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if prev['close'] < prev['open'] and last['close'] > last['open'] and last['close'] > prev['open'] and last['open'] < prev['close']:
        return 'bullish'
    elif prev['close'] > prev['open'] and last['close'] < last['open'] and last['open'] > prev['close'] and last['close'] < prev['open']:
        return 'bearish'
    return None

def analyze():
    tf_data = {tf: get_data(symbol, tf) for tf in ['1d', '4h', '1h']}
    if any(df.empty for df in tf_data.values()):
        return 'WAIT', 0

    fib = apply_fibonacci(tf_data['4h'])
    sr = find_support_resistance(tf_data['1h'])
    close = tf_data['1h']['close'].iloc[-1]

    rsi = RSIIndicator(tf_data['1h']['close']).rsi().iloc[-1]
    pattern = detect_engulfing(tf_data['1h'])

    support_levels = [lvl[1] for lvl in sr if lvl[0] == 'support']
    resistance_levels = [lvl[1] for lvl in sr if lvl[0] == 'resistance']

    ema = EMAIndicator(tf_data['4h']['close'], window=20).ema_indicator().iloc[-1]
    trend = 'UP' if close > ema else 'DOWN'

    print("\n📊 Market Analysis")
    print(f"Close: {close}")
    print(f"Fib 61.8%: {fib['61.8%']}, Fib 38.2%: {fib['38.2%']}")
    print(f"Support levels: {support_levels}")
    print(f"Resistance levels: {resistance_levels}")
    print(f"RSI: {rsi:.2f}")
    print(f"Engulfing pattern: {pattern}")
    print(f"Trend: {trend}")

    buy_signals = 0
    sell_signals = 0

    if trend == 'UP':
        buy_signals += 1
    elif trend == 'DOWN':
        sell_signals += 1

    if any(close >= s - BUFFER_PIPS and close <= s + BUFFER_PIPS for s in support_levels):
        buy_signals += 1
    if any(close >= r - BUFFER_PIPS and close <= r + BUFFER_PIPS for r in resistance_levels):
        sell_signals += 1

    if close < fib['61.8%'] + BUFFER_PIPS:
        buy_signals += 1
    if close > fib['38.2%'] - BUFFER_PIPS:
        sell_signals += 1

    if rsi < RSI_BUY_THRESHOLD:
        buy_signals += 1
    if rsi > RSI_SELL_THRESHOLD:
        sell_signals += 1

    if pattern == 'bullish':
        buy_signals += 1
    elif pattern == 'bearish':
        sell_signals += 1

    def get_confidence(score):
        if score >= 5:
            return "🔴 High", 5
        elif score >= 3:
            return "🟠 Medium", score
        elif score >= 2:
            return "🟡 Low", score
        else:
            return "⚪️ None", 0

    buy_confidence_text, buy_score = get_confidence(buy_signals)
    sell_confidence_text, sell_score = get_confidence(sell_signals)

    print(f"Buy signals: {buy_signals}/5")
    print(f"Sell signals: {sell_signals}/5")
    print(f"Buy Confidence: {buy_confidence_text}")
    print(f"Sell Confidence: {sell_confidence_text}")

    if buy_signals >= 2:
        print(f"📈 Executing BUY (Confidence: {buy_confidence_text})")
        return 'BUY', buy_score
    elif sell_signals >= 2:
        print(f"📉 Executing SELL (Confidence: {sell_confidence_text})")
        return 'SELL', sell_score

    return 'WAIT', 0

def send_order(action, confidence_score):
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"⚠️ Symbol info not found for {symbol}")
        return

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("⚠️ Failed to get tick data.")
        return

    digits = symbol_info.digits
    point = symbol_info.point

    base_lot = 0.01
    lot = base_lot * (confidence_score / 2)
    lot = round(lot, 2)

    if action == "BUY":
        price = tick.ask
        sl = price - 100 * point
        tp = price + 200 * point
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl = price + 100 * point
        tp = price - 200 * point
        order_type = mt5.ORDER_TYPE_SELL

    price = round(price, digits)
    sl = round(sl, digits)
    tp = round(tp, digits)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": magic_number,
        "comment": f"SR-FibBot ({confidence_score}/5)",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ Order failed: {result.retcode} - {result.comment}")
    else:
        print(f"✅ Order placed: {action} | Volume: {lot} | Confidence: {confidence_score}/5")

def run():
    connect()
    while True:
        signal, confidence = analyze()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Trade Signal: {signal}")
        if signal in ["BUY", "SELL"]:
            send_order(signal, confidence)
        time.sleep(60 * 2)

if __name__ == "__main__":
    run()
