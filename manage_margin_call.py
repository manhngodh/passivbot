import ccxt

exchange = ccxt.binance({
    'apiKey': 'CPewxTxRxtlGXFYeyElZ0S9ospdx5jvEE7pPzVTJ2LpZZusxQrszS3egTuNrXi6d',
    'secret': 'h6cxQtD86uCaE0DNRErBsxi6Wv2WgWPgVfUxeW4OuMbeKW0MSEJHdbB8c3THi4F3',
    'options': {
        'defaultType': 'future',
    },
})
def get_current_positions():
    balance = exchange.fetch_balance()
    positions = []
    for info in balance['info']['positions']:
        if float(info['positionAmt']) != 0:
            positions.append({
                'symbol': info['symbol'],
                'side': 'long' if float(info['positionAmt']) > 0 else 'short',
                'quantity': abs(float(info['positionAmt'])),
                'entry_price': float(info['entryPrice'])
            })
    return positions

def calculate_exit_levels(entry_price, position_size, num_levels, level_spacing):
    tp_levels = [entry_price * (1 + level_spacing * i) for i in range(1, num_levels + 1)]
    sl_levels = [entry_price * (1 - level_spacing * i) for i in range(1, num_levels + 1)]
    qty_per_level = position_size / num_levels
    return tp_levels, sl_levels, qty_per_level

def place_exit_orders(position, tp_levels, sl_levels, qty_per_level):
    for tp in tp_levels:
        exchange.create_order(
            symbol=position['symbol'],
            type='limit',
            side='sell' if position['side'] == 'long' else 'buy',
            amount=qty_per_level,
            price=tp
        )

    for sl in sl_levels:
        stop_price = sl
        exchange.create_order(
            symbol=position['symbol'],
            type='stop_limit',
            side='sell' if position['side'] == 'long' else 'buy',
            amount=qty_per_level,
            price=sl * 0.99,  # Assuming stop-limit order, slightly lower than stop price
            params={
                'stopPrice': stop_price
            }
        )

def manage_position_to_avoid_margin_call():
    positions = get_current_positions()
    for position in positions:
        current_price = exchange.fetch_ticker(position['symbol'])['last']
        tp_levels, sl_levels, qty_per_level = calculate_exit_levels(
            position['entry_price'],
            position['quantity'],
            num_levels=10,  # Number of levels to set orders at
            level_spacing=0.01  # 1% spacing between levels
        )
        place_exit_orders(position, tp_levels, sl_levels, qty_per_level)

manage_position_to_avoid_margin_call()
