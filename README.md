# Anti Securities Terminal

A dashboard for retail investors that checks how accurate sell-side analysts have actually been.
It does not forecast anything. It collects public data, scores past analyst calls against what really happened, and uses an LLM only to summarise news and records in neutral language.

PE6201 Emerging AI Technologies, End-of-Course Project, individual submission.

## Run it

```bash
pip install -r requirements.txt
streamlit run APP.py
```

`APP.py` is the entry point. `Anti Securities Report.py` is a byte-identical copy kept for an older deployment path.

The app opens on NVDA. Any ticker can be typed into the search box, for example `MSFT`, `AAPL` or `600519.SS`.
The AI summary features need an API key typed into the page. OpenRouter keys (`sk-or-`), OpenAI keys (`sk-`) and Zhipu GLM keys are supported. The key is kept only for the current browser session and is never written to disk.

## The headline feature: Analyst Call Accuracy Scorecard

Question it answers: on past calls, did the analyst's target price match what happened?

**Sample.** Every historical analyst action with a price target, from Yahoo Finance `upgrades_downgrades`.

**Scoring point.** The close 252 trading days after the call, about 12 months. Sell-side price targets are normally 12-month targets.

**Hit rule.** Judged at the end point, not "touched at any time".
A bullish call, where the target is at or above the price on the call date, is a hit if the price 12 months later is at or above the target.
A bearish call, where the target is below the price on the call date, is a hit if the price 12 months later is at or below the target.

**Error.** Absolute gap between the price 12 months later and the target, as a percent of the target. The scorecard reports the median.

**Not scored.** Calls younger than 252 trading days. They are counted and shown as pending.

**Firm league table.** Only firms with at least 8 scored calls. Smaller samples are hidden because their hit rate means little.

### Two silent failures found and fixed

**1. Stock splits.** Yahoo returns prices adjusted for later splits, but the target prices are stored as the analyst published them. NVDA split 10 for 1 on 10 June 2024. Targets from May 2024 were around 1,100 to 1,350 dollars while the adjusted price for the same days was around 106. Compared directly, every call made before the split looks like a huge miss.
Fix: each target is divided by the product of all splits that happened after its call date.

**2. Dividend adjustment.** Yahoo's default price series is also adjusted for dividends, which pushes old prices down. MSFT closed at 119.84 on 3 June 2019. The default series says 112.31, which is 6.3% lower. Targets are never dividend adjusted.
Fix: the scorecard uses the split-adjusted close without dividend adjustment.

### Results, data pulled on 1 October 2026

| Ticker | Hit rate without split fix | Hit rate with split fix | Median error with fix | Scored calls | Firms | Pending |
|---|---|---|---|---|---|---|
| NVDA | 16.9% | 74.1% | 46.1% | 812 | 55 | 149 |
| AAPL | 32.5% | 49.8% | 18.3% | 842 | 52 | 109 |
| MSFT | 59.5% | 59.5% | 17.3% | 667 | 49 | 105 |

MSFT has not split since 2003, so the split fix should change nothing there. It changes nothing, which is the check that the fix only touches stocks that really split.

### Coverage

Yahoo has dated analyst calls with targets for US stocks only. For A-shares and Hong Kong stocks, for example `600519.SS` and `0700.HK`, Yahoo returns nothing. The scorecard then says there is no coverage for that market. It does not fill the gap with another metric.

No paid data vendor such as Wind or Choice is used.

## Cost per user

The only paid part is the LLM. Market data comes from free public sources: Yahoo Finance through `yfinance` and Chinese market data through `akshare`. Hosting is on the Streamlit Community Cloud free tier.

Every LLM call goes through one function, `llm_chat` in `APP.py`. It reads the real token counts returned by the API and stores them for the session. The page shows them in the panel **AI 用量与每用户成本** at the bottom.

```
cost per call  = input tokens × input price + output tokens × output price
cost per user per month = sessions per month × sum of cost per call in one session
```

Prices are read live from the public OpenRouter price list at `openrouter.ai/api/v1/models`, refreshed every 24 hours. On 1 October 2026:

| Model | Used for | Input, US$ per 1M tokens | Output, US$ per 1M tokens |
|---|---|---|---|
| openai/gpt-4o-mini | short news explanation | 0.15 | 0.60 |
| openai/gpt-4o | full report summary | 2.50 | 10.00 |

If a model's price cannot be found, as with Zhipu `glm-4-flash`, the panel shows the tokens and says the price is not verified. It does not guess a price.

## LLM guardrail

The model only summarises and extracts. Both prompts forbid ratings, buy or sell advice and target prices. All charts, tables and scores come from data sources. The model only writes text summaries.

## Known limits

- Scorecard covers US stocks only. See Coverage.
- The hit rule uses one end point. A target reached in month 6 and lost by month 12 counts as a miss.
- Yahoo's list of analyst actions may not include every call ever made, so the sample is what Yahoo keeps.
- Prices and calls come from third parties. If Yahoo changes its data, results change. The page shows the sample window so a reader can see how fresh the data is.

## Repository layout

| Path | What it is |
|---|---|
| `APP.py` | The whole app, one Streamlit script |
| `Anti Securities Report.py` | Identical copy of `APP.py` |
| `requirements.txt` | Pinned library versions |
| `.streamlit/config.toml` | Theme |
| `_legacy_modules/` | Old split-up version of the code, kept for reference, not run |
| `_scan_shadow.py`, `_v8_patch.py`, `refactor.py`, `remove_except.py` | One-off maintenance scripts from development, not run by the app |
