import ccxt
import os
import time
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    filename='trading_bot.log',
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
initial_distance_pct = 0.01  # Initial distance between orders (1%)
sl_reentry_distance_pct = 0.01  # SL reentry distance (1%)
tp_reentry_distance_pct = 0.01  # TP reentry distance (1%)
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
def fetch_position(symbol):
    try:
        positions = exchange.fetch_positions([symbol])
        for position in positions:
            if position['symbol'] == symbol and float(position['contracts']) > 0:
                logging.info(f'Existing position found: {position}')
                return position
        return None
    except Exception as e:
        logging.error(f'Error fetching position: {str(e)}')
        return None

# Fetch open orders
def fetch_open_orders(symbol):
    try:
        open_orders = exchange.fetch_open_orders(symbol)
        logging.info(f'Open orders: {open_orders}')
        return open_orders
    except Exception as e:
        logging.error(f'Error fetching open orders: {str(e)}')
        return []

# Close all positions and cancel all orders
def close_all_positions_and_orders(symbol):
    try:
        # Cancel all open orders
        open_orders = fetch_open_orders(symbol)
        for order in open_orders:
            exchange.cancel_order(order['id'], symbol)
            logging.info(f'Canceled order: {order["id"]}')

        # Close the position if it exists
        position = fetch_position(symbol)
        if position:
            side = 'sell' if position['side'] == 'long' else 'buy'
            close_order = exchange.create_market_order(symbol, side, position['contracts'])
            logging.info(f'Closed position: {close_order}')

    except Exception as e:
        logging.error(f'Error closing positions or canceling orders: {str(e)}')

# Utility function to get current price
def get_current_price():
    ticker = exchange.fetch_ticker(symbol)
    return ticker['last']

# Calculate price based on percentage
def calculate_price(base_price, percentage):
    return base_price * (1 + percentage)

# Place initial buy and sell limit orders
def place_initial_orders():
    current_price = get_current_price()
    logging.info(f'Current price: {current_price}')

    # Calculate prices for orders based on percentages
    buy_price = calculate_price(current_price, -initial_distance_pct)
    sell_price = calculate_price(current_price, initial_distance_pct)

    logging.info(f'Placing initial buy limit order at {buy_price} and sell limit order at {sell_price}')

    # Place buy limit order
    buy_order = exchange.create_limit_buy_order(symbol, order_size, buy_price)
    logging.info(f'Buy limit order placed: {buy_order}')

    # Place sell limit order
    sell_order = exchange.create_limit_sell_order(symbol, order_size, sell_price)
    logging.info(f'Sell limit order placed: {sell_order}')

    return buy_order, sell_order

# Place stop-loss and take-profit orders after a limit order is filled
def place_stop_loss_take_profit(filled_order):
    order_type = 'buy' if filled_order['side'] == 'buy' else 'sell'
    logging.info(f'Placing SL/TP for the {order_type} order.')

    try:
        # Calculate stop-loss and take-profit prices
        stop_loss_price = calculate_price(filled_order['price'], -stop_loss_buffer_pct) if order_type == 'buy' else calculate_price(filled_order['price'], stop_loss_buffer_pct)
        take_profit_price = calculate_price(filled_order['price'], take_profit_buffer_pct) if order_type == 'buy' else calculate_price(filled_order['price'], -take_profit_buffer_pct)

        if order_type == 'buy':
            stop_loss_order = exchange.create_order(
                symbol,
                type='stop_market',
                side='sell',
                amount=filled_order['amount'],
                price=None,  # Market order
                params={
                    "stopPrice": stop_loss_price,
                    "positionSide": "LONG"
                }
            )
            take_profit_order = exchange.create_order(
                symbol,
                type='take_profit_market',
                side='sell',
                amount=filled_order['amount'],
                price=None,  # Market order
                params={
                    "stopPrice": take_profit_price,
                    "positionSide": "LONG"
                }
            )
        else:
            stop_loss_order = exchange.create_order(
                symbol,
                type='stop_market',
                side='buy',
                amount=filled_order['amount'],
                price=None,  # Market order
                params={
                    "stopPrice": stop_loss_price,
                    "positionSide": "SHORT"
                }
            )
            take_profit_order = exchange.create_order(
                symbol,
                type='take_profit_market',
                side='buy',
                amount=filled_order['amount'],
                price=None,  # Market order
                params={
                    "stopPrice": take_profit_price,
                    "positionSide": "SHORT"
                }
            )

        logging.info(f'SL and TP orders placed: SL at {stop_loss_price}, TP at {take_profit_price}')
        return stop_loss_order, take_profit_order

    except Exception as e:
        logging.error(f'Error placing stop-loss/take-profit: {str(e)}')
        return None, None

# Cancel remaining SL or TP order after one is triggered
def cancel_remaining_order(order):
    try:
        exchange.cancel_order(order['id'], symbol)
        logging.info(f'Canceled remaining SL/TP order: {order}')
    except Exception as e:
        logging.error(f'Error canceling order: {str(e)}')

# Reentry logic after SL or TP is hit
def reentry_order(filled_order, reentry_distance_pct):
    order_type = 'buy' if filled_order['side'] == 'buy' else 'sell'
    trigger_price = filled_order['price']
    new_price = calculate_price(trigger_price, -reentry_distance_pct) if order_type == 'buy' else calculate_price(trigger_price, reentry_distance_pct)

    logging.info(f'Reentry order type: {order_type}, New price: {new_price}')

    if order_type == 'buy':
        new_order = exchange.create_limit_buy_order(symbol, order_size, new_price)
        logging.info(f'Buy reentry order placed at {new_price}: {new_order}')
    else:
        new_order = exchange.create_limit_sell_order(symbol, order_size, new_price)
        logging.info(f'Sell reentry order placed at {new_price}: {new_order}')

    return new_order

# Synchronize with Binance to handle existing positions and orders
def synchronize_with_binance(symbol):
    position = fetch_position(symbol)

    if position:
        # Check if the position matches the current configuration (e.g., leverage, size, entry price)
        # If not, close the position and cancel all orders
        logging.info('Position found, checking configuration...')
        open_orders = fetch_open_orders(symbol)
        if not open_orders:
            # If no open orders are found, create SL and TP orders for the existing position
            logging.info('No SL/TP orders found, creating them...')
            place_stop_loss_take_profit(position)
        else:
            logging.info('Position and orders are in sync.')
    else:
        logging.info('No open positions found, placing initial orders...')
        place_initial_orders()


"""
if position long exist => if SL/TP not exist => place SL/TP for long  or SL exsit but TP not exist => place TP or SL not exist but TP exist => place SL
otherwise => place initial orders
if position short exist => if SL/TP not exist => place SL/TP for long or SL exsit but TP not exist => place TP or SL not exist but TP exist => place SL
otherwise => place initial orders

if position long exist => the SL of long order filled => close long TP order and place reentry long order
                       => the TP of long order filled => close longSL order and place reentry long order
if position sell exist => the SL of sell order filled => close sell TP order and place reentry sell order
                       => the TP of sell order filled => close sell order and place reentry sell order
"""
# Main bot loop
def run_bot():
    # Set leverage before running the bot
    set_leverage(symbol, leverage)

    # Synchronize with Binance
    synchronize_with_binance(symbol)

    while True:
        try:
            # Check the position and take actions if needed
            position = fetch_position(symbol)

            if position:
                logging.info(f'Position detected: {position}')
                open_orders = fetch_open_orders(symbol)
                if not open_orders:
                    # Place SL/TP if not present
                    # place_stop_loss_take_profit(position)
                    # Place SL and TP for the filled order
                    stop_loss_order, take_profit_order = place_stop_loss_take_profit(position)
            else:
                logging.info('No position detected, waiting for new fills.')

            # Monitor for SL/TP triggers and handle them
            while position:
                closed_orders = exchange.fetch_closed_orders(symbol)
                triggered_order = None
                if position and open_orders:
                    if open_orders and any(order['status'] == 'closed' for order in open_orders):
                        triggered_order = next(order for order in open_orders if order['status'] == 'closed')
                if triggered_order:
                    logging.info(f'SL or TP triggered: {triggered_order}')

                    # Cancel the other SL/TP order (if still open)
                    opposite_order = [order for order in open_orders if order['id'] != triggered_order['id']][0]
                    if opposite_order and opposite_order['status'] != 'closed':
                        cancel_remaining_order(opposite_order)

                    # Place reentry order
                    new_order = reentry_order(position, sl_reentry_distance_pct if triggered_order == stop_loss_order else tp_reentry_distance_pct)
                    position = None
                    break

            time.sleep(1)  # Sleep for a short time before checking again

        except Exception as e:
            logging.error(f'Error in bot loop: {str(e)}')
            time.sleep(5)  # Sleep before retrying in case of error

if __name__ == "__main__":
    logging.info('Starting trading bot')
    run_bot()
    
take_profit_order = exchange.create_limit_buy_order(
    symbol,
    amount=1,
    price=18,
    params={"order_tag": "buy_A", "positionSide": "LONG"}
)
buy + SHORT => close short sl => short
# sl long
tp_order = exchange.create_order(symbol, 'STOP_MARKET', 'sell', 1, None, {'stopPrice': 17, "positionSide": "LONG"})
# tp long
tp_order = exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', 'sell', 1, None, {'stopPrice': 25, "positionSide": "LONG"})

# sl long
tp_order = exchange.create_order(symbol, 'STOP_MARKET', 'buy', 1, None, {'stopPrice': 30, "positionSide": "SHORT"})
# tp long
tp_order = exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', 'buy', 1, None, {'stopPrice': 19, "positionSide": "SHORT"})