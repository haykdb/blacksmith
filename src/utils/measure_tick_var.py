import asyncio, json, websockets, numpy as np
from decimal import Decimal

SYMBOL = "flmusdt"
DURATION = 600


async def run():
    url_spot = f"wss://stream.binance.com:9443/ws/{SYMBOL}@bookTicker"
    url_fut = f"wss://fstream.binance.com/ws/{SYMBOL}@bookTicker"

    spot_ask = fut_bid = None
    spreads = []
    last_spread = None

    async def listen(url, tag, q):
        async with websockets.connect(url) as ws:
            async for msg in ws:
                data = json.loads(msg)
                if tag == "spot":
                    q["ask"] = Decimal(data["a"])
                else:
                    q["bid"] = Decimal(data["b"])

    q = {"ask": None, "bid": None}
    await asyncio.gather(
        listen(url_spot, "spot", q), listen(url_fut, "fut", q), collector(q, spreads)
    )


async def collector(q, spreads):
    import time

    start = time.time()
    last_spread = None
    while time.time() - start < DURATION:
        if q["ask"] and q["bid"]:
            spread = q["ask"] - q["bid"]
            if spread != last_spread:
                spreads.append(spread)
                last_spread = spread
        await asyncio.sleep(0)  # yield

    diffs = np.diff(np.array([float(s) for s in spreads]))
    diffs = diffs[abs(diffs) >= 1e-5]
    var = np.var(diffs)
    print(f"Samples: {len(spreads)}, non-zero diffs: {len(diffs)}")
    print(f"tick σ  ≈ {np.sqrt(var):.6f}  r ≈ {var:.6g}")


if __name__ == "__main__":
    asyncio.run(run())
