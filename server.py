from datetime import datetime, timedelta
import os
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("mt5-mcp")

MT5_PATH = os.getenv("MT5_PATH")
ENABLE_LIVE_TRADING = os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"
SYMBOL_ALLOWLIST = {
    s.strip().upper()
    for s in os.getenv("MT5_SYMBOL_ALLOWLIST", "").split(",")
    if s.strip()
}


def connect_mt5():
    if MT5_PATH:
        ok = mt5.initialize(path=MT5_PATH)
    else:
        ok = mt5.initialize()

    if not ok:
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def check_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if SYMBOL_ALLOWLIST and symbol not in SYMBOL_ALLOWLIST:
        raise ValueError(f"Symbol {symbol} is not allowlisted")
    return symbol


@mcp.tool()
def get_account_info() -> dict:
    """Get MT5 account information."""
    connect_mt5()
    info = mt5.account_info()
    mt5.shutdown()

    if info is None:
        raise RuntimeError(f"account_info failed: {mt5.last_error()}")

    return info._asdict()


@mcp.tool()
def get_positions(symbol: Optional[str] = None) -> list[dict]:
    """Get current open positions, optionally filtered by symbol."""
    connect_mt5()

    if symbol:
        symbol = check_symbol(symbol)
        positions = mt5.positions_get(symbol=symbol)
    else:
        positions = mt5.positions_get()

    mt5.shutdown()

    if positions is None:
        return []

    return [p._asdict() for p in positions]


@mcp.tool()
def get_candles(symbol: str, timeframe: str = "M15", count: int = 100) -> list[dict]:
    """Get OHLC candle data from MT5."""
    symbol = check_symbol(symbol)

    timeframe_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }

    if timeframe not in timeframe_map:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    connect_mt5()

    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, timeframe_map[timeframe], 0, count)

    mt5.shutdown()

    if rates is None:
        raise RuntimeError(f"copy_rates_from_pos failed: {mt5.last_error()}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s").astype(str)

    return df.to_dict(orient="records")


@mcp.tool()
def get_trade_history(days: int = 30) -> list[dict]:
    """Get MT5 deal history for the last N days."""
    connect_mt5()

    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)

    deals = mt5.history_deals_get(from_date, to_date)

    mt5.shutdown()

    if deals is None:
        return []

    return [d._asdict() for d in deals]


@mcp.tool()
def place_market_order(
    symbol: str,
    side: str,
    volume: float,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
) -> dict:
    """Place a market buy/sell order. Disabled unless ENABLE_LIVE_TRADING=true."""
    if not ENABLE_LIVE_TRADING:
        raise PermissionError("Live trading is disabled. Set ENABLE_LIVE_TRADING=true to enable.")

    symbol = check_symbol(symbol)
    side = side.lower()

    if side not in ["buy", "sell"]:
        raise ValueError("side must be 'buy' or 'sell'")

    if volume <= 0:
        raise ValueError("volume must be greater than 0")

    connect_mt5()
    mt5.symbol_select(symbol, True)

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        mt5.shutdown()
        raise RuntimeError(f"No tick data for {symbol}")

    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    price = tick.ask if side == "buy" else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": 20260622,
        "comment": "MCP MT5 order",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    if stop_loss:
        request["sl"] = stop_loss
    if take_profit:
        request["tp"] = take_profit

    result = mt5.order_send(request)
    mt5.shutdown()

    if result is None:
        raise RuntimeError(f"order_send failed: {mt5.last_error()}")

    return result._asdict()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
