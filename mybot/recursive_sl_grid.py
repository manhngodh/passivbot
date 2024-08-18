import ccxt
import os
import time
import argparse
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Fetch API keys from environment variables
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')

# Initialize Binance
exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',  # Use 'spot' for spot trading, 'future' for futures trading
    }
})

def config_mode(symbol):
    logger.info("Fetching position mode for symbol: %s", symbol)
    try:
        mode = exchange.fapiprivate_get_positionside_dual()
        logger.info("Current position mode: %s", mode)
    except ccxt.BaseError as e:
        logger.error("Failed to fetch position mode: %s", e)
    # # Set Hedge Mode
    # exchange.fapiprivate_post_positionside_dual({'dualSidePosition': 'true'})

    # # Set One-way Mode
    # exchange.fapiprivate_post_positionside_dual({'dualSidePosition': 'false'})

def set_leverage(symbol, leverage):
    """
    Set leverage for a specific symbol.

    Args:
        symbol (str): The trading pair symbol, e.g., 'BTC/USDT'.
        leverage (int): The leverage level, e.g., 5 for 5x leverage.

    Returns:
        dict: Response from the exchange.
    """
    try:
        response = exchange.fapiprivate_post_leverage({
            'symbol': symbol,
            'leverage': leverage
        })
        print(f"Leverage set to {leverage}x for {symbol}")
        return response
    except Exception as e:
        print(f"Error setting leverage: {e}")

def get_available_balance():
    """
    Get the available balance for futures trading.

    Returns:
        float: The available balance for trading.
    """
    try:
        balance = exchange.fetch_balance(params={"type": "future"})
        total_balance = float(balance['total']['USDT'])  # Adjust for the correct currency if needed
        return total_balance
    except ccxt.BaseError as e:
        logger.error(f"Failed to fetch balance: {e}")
        return 0.0

def calculate_trade_amount(balance_pct, grid_size, current_price):
    """
    Calculate the trade amount in base currency based on the available balance and a percentage allocation.

    Args:
        balance_pct (float): The percentage of available balance to use for trading.
        grid_size (int): Number of grid levels to distribute the trade amount across.
        current_price (float): The current price of the trading symbol (to convert USDT to base currency).

    Returns:
        float: The amount to trade in base currency.
    """
    available_balance = get_available_balance()
    if available_balance == 0:
        logger.error("No available balance for trading.")
        return 0.0
    max_position_size_usdt = available_balance * (balance_pct / 100)
    trade_amount_usdt = max_position_size_usdt / grid_size
    trade_amount_base = trade_amount_usdt / current_price  # Convert USDT amount to base currency amount
    logger.info(f"Calculated trade amount: {trade_amount_base} in base currency (for each grid level, {balance_pct}% of available balance divided by grid size)")
    return trade_amount_base

def place_grid_orders_with_percentage_sl_tp(symbol, grid_size, grid_spacing_pct, balance_pct, tp_pct, sl_pct):
    """
    Place grid orders with specified stop-loss and take-profit percentages.

    Args:
        symbol (str): Trading symbol.
        grid_size (int): Number of grid levels above and below the current price.
        grid_spacing_pct (float): Grid spacing as a percentage of the current price.
        balance_pct (float): Percentage of total balance to allocate to grid positions.
        tp_pct (float): Take Profit percentage.
        sl_pct (float): Stop Loss percentage.

    Returns:
        list: List of orders placed with their details.
    """
    orders = []
    try:
        price = exchange.fetch_ticker(symbol)['last']
        logger.info(f"Current price: {price}")
    except ccxt.BaseError as e:
        logger.error(f"Failed to fetch ticker for {symbol}: {e}")
        return orders
    
    # Calculate the trade amount based on the balance percentage and current price
    trade_amount_base = calculate_trade_amount(balance_pct, grid_size, price)
    if trade_amount_base <= 0:
        return orders
    
    # Create buy orders below the current price
    for i in range(1, grid_size + 1):
        buy_price = price * (1 - (i * grid_spacing_pct / 100))
        try:
            order = exchange.create_limit_buy_order(symbol, trade_amount_base, buy_price, {'positionSide': 'LONG'})
            orders.append({
                'id': order['id'],
                'symbol': symbol,
                'type': 'buy',
                'price': buy_price,
                'sl_price': buy_price * (1 - sl_pct / 100),
                'amount': trade_amount_base
            })
            logger.info(f"Placed buy order at {buy_price}")
            tp_price = buy_price * (1 + tp_pct / 100)
            logger.info(f"Setting TP at {tp_price} for buy order.")
            exchange.create_limit_sell_order(symbol, trade_amount_base, tp_price, {'positionSide': 'LONG'})  # TP
        except ccxt.BaseError as e:
            logger.error(f"Failed to place buy order at {buy_price} - {trade_amount_base}: {e}")

    # Create sell orders above the current price
    for i in range(1, grid_size + 1):
        sell_price = price * (1 + (i * grid_spacing_pct / 100))
        try:
            order = exchange.create_limit_sell_order(symbol, trade_amount_base, sell_price, {'positionSide': 'SHORT'})
            orders.append({
                'id': order['id'],
                'symbol': symbol,
                'type': 'sell',
                'price': sell_price,
                'sl_price': sell_price * (1 + sl_pct / 100),
                'amount': trade_amount_base
            })
            logger.info(f"Placed sell order at {sell_price}")
            tp_price = sell_price * (1 - tp_pct / 100)
            logger.info(f"Setting TP at {tp_price} for sell order.")
            exchange.create_limit_buy_order(symbol, trade_amount_base, tp_price, {'positionSide': 'SHORT'})  # TP
        except ccxt.BaseError as e:
            logger.error(f"Failed to place sell order at {sell_price} - {trade_amount_base}: {e}")

    return orders

def check_and_trigger_stop_loss(orders):
    """
    Check the current price and trigger stop-loss for orders if necessary.

    Args:
        orders (list): List of orders with their details.
    """
    try:
        current_price = exchange.fetch_ticker(orders[0]['symbol'])['last']
    except ccxt.BaseError as e:
        logger.error(f"Failed to fetch ticker for stop-loss check: {e}")
        return

    for order in orders:
        if order['type'] == 'buy' and current_price <= order['sl_price']:
            logger.info(f"Triggering SL for buy order at {order['sl_price']}")
            try:
                exchange.cancel_order(order['id'], order['symbol'])
                exchange.create_market_sell_order(order['symbol'], order['amount'])
            except ccxt.BaseError as e:
                logger.error(f"Failed to trigger stop-loss for buy order: {e}")
        elif order['type'] == 'sell' and current_price >= order['sl_price']:
            logger.info(f"Triggering SL for sell order at {order['sl_price']}")
            try:
                exchange.cancel_order(order['id'], order['symbol'])
                exchange.create_market_buy_order(order['symbol'], order['amount'])
            except ccxt.BaseError as e:
                logger.error(f"Failed to trigger stop-loss for sell order: {e}")

def adjust_grid(symbol, grid_size, grid_spacing_pct, balance_pct, tp_pct, sl_pct):
    """
    Adjust grid orders based on the current market price.

    Args:
        symbol (str): Trading symbol.
        grid_size (int): Number of grid levels above and below the current price.
        grid_spacing_pct (float): Grid spacing as a percentage of the current price.
        balance_pct (float): Percentage of total balance to allocate to grid positions.
        tp_pct (float): Take Profit percentage.
        sl_pct (float): Stop Loss percentage.
    """
    try:
        open_orders = exchange.fetch_open_orders(symbol)
        price = exchange.fetch_ticker(symbol)['last']
    except ccxt.BaseError as e:
        logger.error(f"Failed to adjust grid for {symbol}: {e}")
        return

    for order in open_orders:
        order_id = order['id']
        order_price = float(order['price'])
        order_side = order['side']

        # Only adjust orders if they are significantly away from the current price
        tolerance = grid_spacing_pct / 2 / 100

        if order_side == 'buy' and order_price > price * (1 + tolerance):
            try:
                exchange.cancel_order(order_id, symbol)
                new_buy_price = price * (1 - grid_spacing_pct / 100)
                trade_amount_base = calculate_trade_amount(balance_pct, grid_size, price)
                exchange.create_limit_buy_order(symbol, trade_amount_base, new_buy_price)
                logger.info(f"Replaced buy order at {new_buy_price}")
            except ccxt.BaseError as e:
                logger.error(f"Failed to replace buy order: {e}")

        elif order_side == 'sell' and order_price < price * (1 - tolerance):
            try:
                exchange.cancel_order(order_id, symbol)
                new_sell_price = price * (1 + grid_spacing_pct / 100)
                trade_amount_base = calculate_trade_amount(balance_pct, grid_size, price)
                exchange.create_limit_sell_order(symbol, trade_amount_base, new_sell_price)
                logger.info(f"Replaced sell order at {new_sell_price}")
            except ccxt.BaseError as e:
                logger.error(f"Failed to replace sell order: {e}")

def recursive_grid_trading_with_manual_sl_tp(symbol, grid_size, grid_spacing_pct, balance_pct, tp_pct, sl_pct, sleep_time=60):
    """
    Continuously run the grid trading strategy with manual SL and TP.

    Args:
        symbol (str): Trading symbol.
        grid_size (int): Number of grid levels above and below the current price.
        grid_spacing_pct (float): Grid spacing as a percentage of the current price.
        balance_pct (float): Percentage of total balance to allocate to grid positions.
        tp_pct (float): Take Profit percentage.
        sl_pct (float): Stop Loss percentage.
        sleep_time (int): Time in seconds between grid adjustments.
    """
    orders = place_grid_orders_with_percentage_sl_tp(symbol, grid_size, grid_spacing_pct, balance_pct, tp_pct, sl_pct)

    while True:
        check_and_trigger_stop_loss(orders)
        adjust_grid(symbol, grid_size, grid_spacing_pct, balance_pct, tp_pct, sl_pct)
        time.sleep(sleep_time)  # Wait before next iteration

def main():
    parser = argparse.ArgumentParser(description="Grid Trading Bot with Manual Stop Loss and Take Profit")
    
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--grid_size", type=int, default=3, help="Number of grid levels above and below the current price")
    parser.add_argument("--grid_spacing_pct", type=float, default=1.0, help="Grid spacing as a percentage of the current price")
    parser.add_argument("--balance_pct", type=float, default=50.0, help="Percentage of available balance to use per trade")
    parser.add_argument("--tp_pct", type=float, default=2.0, help="Take Profit percentage")
    parser.add_argument("--sl_pct", type=float, default=1.0, help="Stop Loss percentage")
    parser.add_argument("--leverage", type=int, default=30, help="Leverage")
    parser.add_argument("--sleep_time", type=int, default=60, help="Time in seconds between grid adjustments")
    
    args = parser.parse_args()

    # Validate inputs
    if args.grid_size <= 0:
        logger.error("Grid size must be greater than 0.")
        return
    if args.grid_spacing_pct <= 0:
        logger.error("Grid spacing percentage must be greater than 0.")
        return
    if args.balance_pct <= 0 or args.balance_pct > 100:
        logger.error("Balance percentage must be between 0 and 100.")
        return
    if args.tp_pct <= 0:
        logger.error("Take Profit percentage must be greater than 0.")
        return
    if args.sl_pct <= 0:
        logger.error("Stop Loss percentage must be greater than 0.")
        return
    if args.sleep_time <= 0:
        logger.error("Sleep time must be greater than 0.")
        return

    config_mode(args.symbol)
    set_leverage(args.symbol, args.leverage)
    # Run the bot with the calculated trade amount
    recursive_grid_trading_with_manual_sl_tp(
        symbol=args.symbol,
        grid_size=args.grid_size,
        grid_spacing_pct=args.grid_spacing_pct,
        balance_pct=args.balance_pct,
        tp_pct=args.tp_pct,
        sl_pct=args.sl_pct,
        sleep_time=args.sleep_time
    )

if __name__ == "__main__":
    main()
