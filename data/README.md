# Data used in this project

All data is public market data. Nothing here is hand-made or edited. Every file was produced by `python tools/build_snapshot.py`, run on a local machine on **1 October 2026**.

## Sources

| Source | Library | What it provides | Used for |
|---|---|---|---|
| Yahoo Finance | `yfinance` 1.5.2 | Prices, splits, company profile, financial statements, analyst ratings, **dated analyst actions with price targets** (`upgrades_downgrades`) | Scorecard, stock pages |
| Eastmoney, Sina, Baidu, China Money | `akshare` 1.18.79 | A-share data, Shibor, China bond yields, macro calendar, news | Market overview panels |
| OpenRouter price list | public JSON at `openrouter.ai/api/v1/models` | LLM price per million tokens | Cost per user |

## Files

### `scorecard_calls.csv` — 6,346 rows

Every analyst call that could be scored, for the 10 stocks in `snapshot.UNIVERSE`. One row per call.

| Column | Meaning |
|---|---|
| `ticker` | Stock |
| `firm` | Research firm that made the call |
| `date` | Trading day of the call |
| `price_at_call` | Close on that day, split adjusted, not dividend adjusted |
| `target` | The firm's price target, converted to today's share count by dividing by all later splits |
| `price_at_horizon` | Close 252 trading days later, about 12 months |
| `bullish` | True if the target was at or above the price on the call date |
| `hit` | Bullish call: price at horizon ≥ target. Bearish call: price at horizon ≤ target |
| `abs_err_pct` | Absolute gap between price at horizon and target, as a percent of target |

Calls younger than 252 trading days are not in this file. They are counted as pending in `snapshots/meta.json`.

### `buy_rating_returns.csv` — 5,247 rows

Every buy-type rating (Buy, Strong Buy, Outperform, Overweight and similar) and what the stock did over the next 252 trading days. This is the prototype data for the planned paid feature, the analyst track record summary.

| Column | Meaning |
|---|---|
| `ticker`, `firm`, `date` | As above |
| `grade` | The rating the firm moved to |
| `ret` | Return over the next 252 trading days, as a decimal. 0.25 means up 25% |

### `snapshots/` — backup for the cloud deployment

When the app runs on Streamlit Community Cloud, Yahoo rate limits the shared server address and most company data comes back empty. `snapshot.py` detects this and loads these files instead. The page then shows a notice with the snapshot date.

| File | Content |
|---|---|
| `<TICKER>/all_data.pkl` | Full data bundle for one stock, exactly as `market_data.fetch_all_data()` returned it |
| `<TICKER>/bench.pkl` | Peer valuation benchmark |
| `<TICKER>/track.pkl` | Scorecard result |
| `meta.json` | Build date and a summary per stock, shown below |

The `.pkl` files are Python pickles written by this repository's own build script. Load them only from this repository.

## Summary per stock

| Ticker | Scored calls | Pending | Firms | Hit rate | Median abs error | Call window | Buy ratings | Rose 12m after buy | Median 12m return after buy |
|---|---|---|---|---|---|---|---|---|---|
| NVDA | 811 | 149 | 55 | 74.2% | 46.1% | 2017-08-11 to 2025-09-29 | 730 | 92.9% | 61.2% |
| MSFT | 667 | 105 | 49 | 59.5% | 17.3% | 2016-11-17 to 2025-09-26 | 640 | 77.3% | 26.4% |
| AAPL | 838 | 109 | 52 | 49.6% | 18.3% | 2018-12-07 to 2025-09-26 | 621 | 89.4% | 25.1% |
| AMZN | 839 | 148 | 60 | 43.4% | 17.6% | 2020-02-05 to 2025-09-24 | 821 | 74.4% | 16.2% |
| GOOGL | 813 | 148 | 57 | 59.3% | 25.0% | 2017-10-27 to 2025-09-25 | 727 | 75.7% | 31.6% |
| META | 392 | 0 | 51 | 81.1% | 42.6% | 2021-05-03 to 2024-09-30 | 347 | 93.9% | 72.1% |
| TSLA | 834 | 94 | 45 | 32.3% | 35.1% | 2019-10-24 to 2025-09-26 | 428 | 68.7% | 24.4% |
| AVGO | 405 | 92 | 38 | 75.6% | 25.5% | 2016-10-04 to 2025-09-15 | 381 | 91.6% | 45.0% |
| AMD | 482 | 155 | 47 | 61.6% | 41.6% | 2016-11-22 to 2025-09-09 | 364 | 75.0% | 51.7% |
| JPM | 265 | 40 | 28 | 64.5% | 17.2% | 2016-11-30 to 2025-09-29 | 188 | 84.0% | 28.8% |
| **All** | **6,346** | | **90** | **57.1%** | **25.0%** | | **5,247** | **81.7%** | **32.2%** |

## Known limits of this data

1. **Selection bias.** The 10 stocks are today's largest US companies. They were picked in 2026, after they had already risen a lot. In this sample 88.9% of calls are bullish, bullish calls hit 62.9% of the time and bearish calls only 10.6%. Part of that gap comes from how the sample was chosen, not from analyst skill. The same is true for "81.7% of buy ratings were followed by a rise": most of it is the market going up. A fair version needs stocks chosen without hindsight and returns measured against an index.
2. **US only.** Yahoo has no dated analyst calls for A-shares or Hong Kong stocks. The app says so on the page and does not substitute another measure.
3. **Yahoo's record is incomplete.** For example, META has no calls after 30 September 2024 in Yahoo's list, so it has no pending calls at all. The sample is whatever Yahoo keeps.
4. **Firm, not person.** Yahoo names the research firm, not the individual analyst.
5. **One end point.** A target reached in month 6 and lost by month 12 counts as a miss.
