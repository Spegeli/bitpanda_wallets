DOMAIN = "bitpanda_wallets"
CONF_API_KEY = "api_key"
CONF_WALLET = "wallet"
CONF_CURRENCY = "currency"

BITPANDA_API_URL = "https://api.bitpanda.com/v1"
UPDATE_INTERVAL = 5

DEFAULT_FIAT_CURRENCY = "EUR"
FIAT_CURRENCIES = ["EUR", "USD", "CHF", "GBP", "TRY", "PLN", "HUF", "CZK", "SEK", "DKK"]

WALLET_TYPES = {
    "FIAT": "Fiat",
    "CRYPTOCOIN": "Crypto",
    "LEVERAGE": "Leverage",
    "INDEX": "Crypto Indices",
#    "SECURITYTOKEN": "Security token",    
    "STOCK": "Stocks",
    "ETF": "ETFs",
    "ETC": "Commodities", 
    "METAL": "Metals"
}
