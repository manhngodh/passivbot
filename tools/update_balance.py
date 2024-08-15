import ccxt
import os
import time
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fetch API keys from environment variables
api_key = os.getenv('BINANCE_API_KEY')
secret_key = os.getenv('BINANCE_SECRET_KEY')
telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

# Initialize Binance with futures enabled
exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': secret_key,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future'  # Ensure that futures are enabled
    },
})

# Set the API to use the testnet for safety (comment out for live trading)
# exchange.set_sandbox_mode(True)

# Initialize last known values to None
last_total_balance = None
last_unrealized_pnl = None
last_available_balance = None
last_margin_ratio = None

def send_telegram_message(message):
    url = f'https://api.telegram.org/bot{telegram_bot_token}/sendMessage'
    data = {
        'chat_id': telegram_chat_id,
        'text': message
    }
    response = requests.post(url, data=data)
    if response.status_code == 200:
        print("Message sent successfully")
    else:
        print(f"Failed to send message: {response.status_code}")

def fetch_and_notify():
    global last_total_balance, last_unrealized_pnl, last_available_balance, last_margin_ratio
    
    balance = exchange.fetch_balance(params={"type": "future"})
    positions = balance['info']['positions']

    # Extract balance metrics
    total_balance = float(balance['info']['totalMarginBalance'])  # Total margin balance
    unrealized_pnl = float(balance['info']['totalUnrealizedProfit'])  # Total unrealized PnL
    available_balance = float(balance['info']['availableBalance'])  # Available balance

    # Calculate margin ratio
    margin_ratio = calculate_margin_ratio(positions, total_balance)

    # Determine if there's a significant change
    if (last_total_balance is None or 
        abs(total_balance - last_total_balance) / last_total_balance > 0.01 or
        abs(unrealized_pnl - last_unrealized_pnl) / last_unrealized_pnl > 0.01 or
        abs(available_balance - last_available_balance) / last_available_balance > 0.01 or
        abs(margin_ratio - last_margin_ratio) / last_margin_ratio > 0.01):
        
        # Update last known values
        last_total_balance = total_balance
        last_unrealized_pnl = unrealized_pnl
        last_available_balance = available_balance
        last_margin_ratio = margin_ratio

        # Evaluate risk level
        if margin_ratio < 0.2:
            risk_level = "Low"
        elif 0.2 <= margin_ratio < 0.5:
            risk_level = "Medium"
        else:
            risk_level = "High"

        # Format the message
        message = (
            f"Total Balance: {total_balance:.2f} USDT\n"
            f"Unrealized PnL: {unrealized_pnl:.2f} USDT\n"
            f"Available Balance: {available_balance:.2f} USDT\n"
            f"Margin Ratio: {margin_ratio:.2%}\n"
            f"Risk Level: {risk_level}"
        )

        # Send the message to Telegram
        send_telegram_message(message)

def calculate_margin_ratio(positions, total_balance):
    total_margin = 0
    total_position_value = 0
    
    for position in positions:
        if float(position['positionAmt']) != 0:  # Only consider open positions
            margin = float(position.get('initialMargin', 0))  # Safe get for initial margin
            position_value = abs(float(position['notional']))  # Use 'notional' directly for position value
            total_margin += margin
            total_position_value += position_value

    if total_position_value == 0:
        return 0
    
    # Margin ratio formula: total_margin / total_balance
    margin_ratio = total_margin / total_balance
    
    return margin_ratio

def main():
    while True:
        try:
            fetch_and_notify()
        except Exception as e:
            print(f"An error occurred: {e}")
            send_telegram_message(f"An error occurred: {e}")
        time.sleep(120)  # Wait for 1 minute before fetching data again

if __name__ == "__main__":
    main()
