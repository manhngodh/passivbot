import ccxt
import os
import time
import logging
from dotenv import load_dotenv
import traceback

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
    )

# Initialize Binance for futures trading
exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_API_SECRET'),
    'options': {
        'defaultType': 'future',  # Enables futures trading
    },
    'enableRateLimit': True,
})


# Constants
symbol = 'AVAXUSDT'  # Trading pair
initial_distance_pct = 0.005  # Initial distance between orders (1%)
max_distance_pct = 0.03  # Maximum distance between orders (5%)
stop_loss_buffer_pct = 0.005  # Stop-loss buffer (0.5%)
take_profit_buffer_pct = 0.015  # Take-profit buffer (1%)
order_size = 2  # Order size (in BTC)
leverage = 30

# Set leverage using fapiprivate_post_leverage
def set_leverage(symbol, leverage):
    try:
        response = exchange.fapiprivate_post_leverage({
            'symbol': symbol.replace('/', ''),  # Remove '/' from the symbol
            'leverage': leverage
        })
        logging.info(f'Leverage set to {leverage}x for {symbol}: {response}')
    except Exception as e:
        logging.error(f'Error setting leverage: {str(e)}')

# Fetch existing positions
def fetch_positions(symbol):
    positions = []
    try:
        positions = exchange.fetch_positions([symbol])
        for position in positions:
            if position['symbol'] == symbol and float(position['contracts']) > 0:
                positions.append(position)
        return positions
    except Exception as e:
        logging.error(f'Error fetching position: {str(e)}')
        return positions

# Fetch open orders
def fetch_open_orders(symbol):
    try:
        open_orders = exchange.fetch_open_orders(symbol)
        return open_orders
    except Exception as e:
        logging.error(f'Error fetching open orders: {str(e)}')
        return []

# Utility function to get current price
def get_current_price():
    ticker = exchange.fetch_ticker(symbol)
    return ticker['last']

# Calculate price based on percentage
def calculate_price(base_price, percentage):
    return base_price * (1 + percentage)

# Cancel remaining SL or TP order after one is triggered
def cancel_order(order):
    try:
        exchange.cancel_order(order['id'], symbol)
    except Exception as e:
        logging.error(f'Error canceling order: {str(e)}')

# Function to log essential order details
def log_essential_orders(message, orders):
    logging.info(message)
    for order in orders:
        logging.info(
            f"Order ID: {order['id']}, "
            f"Side: {order['side'].capitalize()}, "
            f"Type: {order['type'].replace('_', ' ').title()}, "
            f"Price: {order['price'] if order['price'] else 'Market'}, "
            f"Qty: {order['amount']}, "
            f"Status: {order['status'].capitalize()}"
        )

# Function to log essential order details
def log_essential_order(order):
    logging.info(
        f"Order ID: {order['id']}, "
        f"Side: {order['side'].capitalize()}, "
        f"Type: {order['type'].replace('_', ' ').title()}, "
        f"Price: {order['price'] if order['price'] else 'Market'}, "
        f"Qty: {order['amount']}, "
        f"Status: {order['status'].capitalize()}"
    )

# Function to log essential position details
def log_essential_position(message, position):
    logging.info(message)
    logging.info(
        f"Side: {position['side'].capitalize()}, "
        f"Qty: {position['contracts']}, "
        f"Entry: {position['entryPrice']}, "
        f"Mark: {position['markPrice']}, "
        f"Unrealized PnL: {position['unrealizedPnl']}"
    )

"""
if position long exist => if SL/TP not exist => place SL/TP for long  or SL exsit but TP not exist => place TP or SL not exist but TP exist => place SL
otherwise => place initial orders
if position short exist => if SL/TP not exist => place SL/TP for short or SL exsit but TP not exist => place TP or SL not exist but TP exist => place SL
otherwise => place initial orders

if position long exist => the SL of long order filled => close long TP order and place reentry long order
                       => the TP of long order filled => close longSL order and place reentry long order
if position short exist => the SL of short order filled => close short TP order and place reentry short order
                       => the TP of short order filled => close short order and place reentry short order
"""
# Main bot loop
def run_bot():
    # Set leverage before running the bot
    set_leverage(symbol, leverage)
    logging.info(f'Starting the bot for {symbol} with leverage {leverage}x')
    while True:
        logging.info('Checking for new opportunities...')
        try:
            current_price = get_current_price()
            positions = fetch_positions(symbol)
            open_orders = fetch_open_orders(symbol)
            log_essential_orders('Open orders:', open_orders)
            # check if positions exist or not
            if not any(position['side'] == 'long' for position in positions):
                # check SL and TP for long position, because there no position so they would be closed
                redundent_orders = list(filter(lambda order: order['side'] == 'sell' and (order['type'] == 'take_profit_market' or order['type'] == 'stop_market'), open_orders))
                if redundent_orders:
                    for order in redundent_orders:
                        cancel_order(order)
                    log_essential_orders('Long redundent orders are closed:', redundent_orders)
                
                long_orders = [order for order in open_orders if order['side'] == 'buy' and order['type'] == 'limit']
                # no long position exist => place initial long order
                if not any(long_orders):
                    long_price = calculate_price(current_price, -initial_distance_pct)
                    long_order = exchange.create_limit_buy_order(symbol, order_size, long_price, params={'positionSide': 'LONG'})
                    log_essential_orders(f'Buy limit order placed because no order before:', [long_order])
                else: # no long position exist but existed long order too far from current price => cancel long order and place new long order
                    for order in long_orders:
                        if abs(order['price'] - current_price) > max_distance_pct * current_price:
                            cancel_order(order)
                            long_price = calculate_price(current_price, -initial_distance_pct)
                            long_order = exchange.create_limit_buy_order(symbol, order_size, long_price, params={'positionSide': 'LONG'})
                            log_essential_orders(f'Buy limit order placed because old order outdated:', [long_order])
                
            if not any(position['side'] == 'short' for position in positions):
                # check SL and TP for short position, because there no position so they would be closed
                redundent_orders = list(filter(lambda order: order['side'] == 'buy' and (order['type'] == 'take_profit_market' or order['type'] == 'stop_market'), open_orders))
                if redundent_orders:
                    for order in redundent_orders:
                        cancel_order(order)
                    log_essential_orders('Short redundent orders are closed:', redundent_orders)

                short_order = [order for order in open_orders if order['side'] == 'sell' and order['type'] == 'limit']
                # no short position exist => place initial short order
                if not any(order['side'] == 'sell' for order in open_orders):
                    short_price = calculate_price(current_price, initial_distance_pct)
                    short_order = exchange.create_limit_sell_order(symbol, order_size, short_price, params={'positionSide': 'SHORT'})
                    log_essential_orders(f'Sell limit order placed because no order before:', [short_order])
                else: # no short position exist but existed short order  too far from current price => cancel short order and place new short order
                    for order in short_order:
                        if abs(order['price'] - current_price) > max_distance_pct * current_price:
                            cancel_order(order)
                            short_price = calculate_price(current_price, initial_distance_pct)
                            short_order = exchange.create_limit_sell_order(symbol, order_size, short_price, params={'positionSide': 'SHORT'})
                            log_essential_orders(f'Sell limit order placed because old order outdated:', [short_order])

            for position in positions:
                log_essential_position('Position:', position)
                entry_price = float(position['info']['entryPrice'])
                quantity = abs(float(position['info']['positionAmt']))
                if position['side'] == 'long':
                    # if the position is ecceeded the stop loss => cancel the position
                    if position['unrealizedProfit'] < -stop_loss_buffer_pct * entry_price * quantity:
                        exchange.create_market_sell_order(symbol, quantity, params={'positionSide': 'LONG'})
                        log_essential_position(f'Long position closed because of stop loss:', position)
                        continue
                    order_params = {
                        "positionSide": "LONG"
                    }
                    
                    sl_exists = any(order['type'] == 'stop_market' and order['side'] == 'sell' for order in open_orders)
                    tp_exists = any(order['type'] == 'take_profit_market' and order['side'] == 'sell' for order in open_orders)
                    if not sl_exists:
                        # create sl for long
                        stop_loss_price = calculate_price(entry_price, -stop_loss_buffer_pct)
                        order_params['stopPrice'] = stop_loss_price
                        stop_loss_order = exchange.create_order(symbol, 'stop_market', 'sell', quantity, params=order_params)
                        log_essential_orders(f'Stop loss order placed for long position:', [stop_loss_order])
                    if not tp_exists:
                        # create tp for long
                        take_profit_price = calculate_price(entry_price, take_profit_buffer_pct)
                        order_params['stopPrice' ] = take_profit_price
                        take_profit_order = exchange.create_order(symbol, 'take_profit_market', 'sell', quantity, params=order_params)
                        log_essential_orders(f'Take profit order placed for long position:', [take_profit_order])
                elif position['side'] == 'short':
                    # if the position is ecceeded the stop loss => cancel the position
                    if position['unrealizedProfit'] < -stop_loss_buffer_pct * entry_price * quantity:
                        exchange.create_market_buy_order(symbol, quantity, params={'positionSide': 'SHORT'})
                        log_essential_position(f'Short position closed because of stop loss:', position)
                        continue
                    order_params = {
                        "positionSide": "SHORT"
                    }
                    sl_exists = any(order['type'] == 'stop_market' and order['side'] == 'buy' for order in open_orders)
                    tp_exists = any(order['type'] == 'take_profit_market' and order['side'] == 'buy' for order in open_orders)
                    if not sl_exists:
                        # create sl for short
                        stop_loss_price = calculate_price(entry_price, stop_loss_buffer_pct)
                        order_params['stopPrice'] = stop_loss_price
                        stop_loss_order = exchange.create_order(symbol, 'stop_market', 'buy', quantity, params=order_params)
                        log_essential_orders(f'Stop loss order placed for short position:', [stop_loss_order])
                    if not tp_exists:
                        # create tp for short
                        take_profit_price = calculate_price(entry_price, -take_profit_buffer_pct)
                        order_params['stopPrice' ] = take_profit_price
                        take_profit_order = exchange.create_order(symbol, 'take_profit_market', 'buy', quantity, params=order_params)
                        log_essential_orders(f'Take profit order placed for short position:', [take_profit_order])
            time.sleep(30)
        except Exception as e:
            logging.error(f'Error in bot loop: {str(e)}')
            logging.error(traceback.format_exc())
            time.sleep(360)  # Sleep before retrying in case of error
if __name__ == "__main__":
    logging.info('Starting trading bot')
    run_bot()

def test():
    # sl long
    tp_order = exchange.create_order(symbol, 'STOP_MARKET', 'sell', 1, None, {'stopPrice': 17, "positionSide": "LONG"})
    # tp long
    tp_order = exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', 'sell', 1, None, {'stopPrice': 25, "positionSide": "LONG"})

    # sl short
    tp_order = exchange.create_order(symbol, 'STOP_MARKET', 'buy', 1, None, {'stopPrice': 30, "positionSide": "SHORT"})
    # tp short
    tp_order = exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', 'buy', 1, None, {'stopPrice': 19, "positionSide": "SHORT"})