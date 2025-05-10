import requests
import pandas as pd

VOLUME_THRESHOLD = 50_000_000  # $50M
EXCLUDED = {"USDCUSDT", "BUSDUSDT", "TUSDUSDT", "BTCUSDT", "ETHUSDT"}

def get_funding_rates():
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    response = requests.get(url)
    data = response.json()
    return {item["symbol"]: float(item["lastFundingRate"]) for item in data}

def get_top_symbols(limit=20):
    url = "https://api.binance.com/api/v3/ticker/24hr"
    response = requests.get(url)
    data = pd.DataFrame(response.json())

    # Filter USDT pairs
    data = data[data["symbol"].str.endswith("USDT")]
    data["quoteVolume"] = data["quoteVolume"].astype(float)

    # Exclude stablecoins and overly efficient pairs
    data = data[~data["symbol"].isin(EXCLUDED)]
    data = data[data["quoteVolume"] > VOLUME_THRESHOLD]

    # Calculate volatility
    data["lastPrice"] = data["lastPrice"].astype(float)
    data["highPrice"] = data["highPrice"].astype(float)
    data["lowPrice"] = data["lowPrice"].astype(float)
    data["volatility_pct"] = (data["highPrice"] - data["lowPrice"]) / data["lastPrice"]

    # Add funding rates
    funding = get_funding_rates()
    data["fundingRate"] = data["symbol"].map(funding).fillna(0)

    # Score = liquidity × volatility × (1 + |funding| × 10)
    data["score"] = data["quoteVolume"] * data["volatility_pct"] * (1 + abs(data["fundingRate"]) * 10)

    top = data.sort_values("score", ascending=False).head(limit)
    return top[["symbol", "quoteVolume", "volatility_pct", "fundingRate", "score"]]

if __name__ == "__main__":
    top_symbols = get_top_symbols()
    print("\nTop Market-Neutral Candidates:\n")
    print(top_symbols.to_string(index=False))
