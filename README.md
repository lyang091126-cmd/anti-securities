# Anti Securities Terminal

A dashboard for retail investors that checks how accurate sell-side analysts have actually been.
It does not forecast anything. It collects public data, scores past analyst calls against what really happened, and uses an LLM only to summarise news and records in neutral language.

PE6201 Emerging AI Technologies, End-of-Course Project, individual submission.

**Live app:** https://antisecurities.streamlit.app
**Product documentation** with persona, inputs, outputs, architecture diagram and metrics: [`PRODUCT.md`](PRODUCT.md)
**Data used:** [`data/README.md`](data/README.md) · **Evaluations:** [`evals/README.md`](evals/README.md)

## Run it

Python 3.12 or 3.13.

```bash
pip install -r requirements.txt
streamlit run APP.py
```

The app opens on NVDA. Any ticker can be typed into the search box, for example `MSFT`, `AAPL` or `600519.SS`. The first full page load takes one to two minutes because it calls many live data sources.

The AI features need an API key typed into the page. OpenRouter keys (`sk-or-`), OpenAI keys (`sk-`) and Zhipu GLM keys are supported. The key is kept only for the current browser session and is never written to disk. Everything else works without a key.

To see how the app behaves on the cloud host, where Yahoo rate limits company data, run it with `ANTI_FORCE_SNAPSHOT=1`. The stock pages then load from the dated snapshot in `data/snapshots/`.

## Run the evaluations

```bash
python evals/run_evals.py          # 18 offline tests, no network
python evals/eval_split_fix.py     # price convention experiment on real data
```

`evals/eval_guardrail.py` tests the no-advice guardrail and needs an API key. See [`evals/README.md`](evals/README.md).

## Rebuild the data

```bash
python tools/build_snapshot.py
```

Run this on a local machine, not on the cloud host. It rewrites `data/scorecard_calls.csv`, `data/buy_rating_returns.csv` and `data/snapshots/`.

## Repository layout

| Path | What it is |
|---|---|
| `APP.py` | Streamlit entry point. Pages and layout only. The header comment maps every section of the page |
| `market_data.py` | Data layer: full data bundle for one stock, peer valuation benchmark |
| `scorecard.py` | Core algorithm: analyst call accuracy, split adjustment, returns after buy ratings |
| `llm_cost.py` | LLM provider routing, live prices, cost arithmetic, no-advice detector, shared system prompt |
| `snapshot.py` | Detects Yahoo rate limiting and switches to the dated snapshot |
| `tools/build_snapshot.py` | Builds the data files and snapshots |
| `data/` | Data used in the project, with its own README |
| `evals/` | Unit tests and experiments, with their own README and results |
| `PRODUCT.md` | Persona, inputs, outputs, architecture, metrics targeted and reached |
| `requirements.txt` | Pinned library versions |
| `Anti Securities Report.py` | Identical copy of `APP.py` kept for an older deployment path |
| `_legacy_modules/`, `_scan_shadow.py`, `_v8_patch.py`, `refactor.py`, `remove_except.py` | Old code and one-off maintenance scripts from development, not run by the app |

Every Python module starts with a description of what it does, what it exposes and how it fails.

## The headline feature: Analyst Call Accuracy Scorecard

Question it answers: on past calls, did the analyst's target price match what happened?

**Sample.** Every historical analyst action with a price target, from Yahoo Finance `upgrades_downgrades`.

**Scoring point.** The close 252 trading days after the call, about 12 months. Sell-side price targets are normally 12-month targets.

**Hit rule.** Judged at the end point, not "touched at any time". A bullish call, where the target is at or above the price on the call date, is a hit if the price 12 months later is at or above the target. A bearish call is a hit if the price 12 months later is at or below the target.

**Error.** Absolute gap between the price 12 months later and the target, as a percent of the target. The scorecard reports the median.

**Not scored.** Calls younger than 252 trading days. They are counted and shown as pending.

**Firm league table.** Only firms with at least 8 scored calls.

### Two silent failures found and fixed

**Stock splits.** Yahoo returns prices adjusted for later splits, but it stores targets as the analyst published them. NVDA split 10 for 1 in June 2024. Targets from May 2024 were 1,100 to 1,350 dollars while the adjusted price was about 106, so every earlier call looked like a huge miss. Fix: each target is divided by all splits after its call date.

**Dividend adjustment.** Yahoo's default prices are also adjusted for dividends, which pushes old prices down. MSFT closed at 119.84 on 3 June 2019, but the default series says 112.31. Targets are never dividend adjusted. Fix: the scorecard uses prices adjusted for splits only.

Both fixes are checked with a control group in [`evals/README.md`](evals/README.md). Stocks with no split are unchanged by the split fix, and stocks that pay no dividend are unchanged by the dividend fix.

### Results, data built on 1 October 2026

| Ticker | Hit rate | Median error | Scored calls | Firms |
|---|---|---|---|---|
| NVDA | 74.2% | 46.1% | 811 | 55 |
| MSFT | 59.5% | 17.3% | 667 | 49 |
| AAPL | 49.6% | 18.3% | 838 | 52 |
| AMZN | 43.4% | 17.6% | 839 | 60 |
| GOOGL | 59.3% | 25.0% | 813 | 57 |
| META | 81.1% | 42.6% | 392 | 51 |
| TSLA | 32.3% | 35.1% | 834 | 45 |
| AVGO | 75.6% | 25.5% | 405 | 38 |
| AMD | 61.6% | 41.6% | 482 | 47 |
| JPM | 64.5% | 17.2% | 265 | 28 |
| **All** | **57.1%** | **25.0%** | **6,346** | **90** |

These 10 stocks are today's winners, which favours bullish calls. See the limits in [`data/README.md`](data/README.md).

### Coverage

Yahoo has dated analyst calls for US stocks only. For A-shares and Hong Kong stocks the scorecard says there is no coverage for that market and does not fill the gap with another measure. No paid vendor such as Wind or Choice is used.

## Cost per user

Market data comes from free public sources and hosting is on the Streamlit Community Cloud free tier, so the only paid part is the LLM. Every call goes through `llm_chat` in `APP.py`, which records the real token counts. The page shows them in the panel **AI 用量与每用户成本** at the bottom.

```
cost per call           = input tokens × input price + output tokens × output price
cost per user per month = sessions per month × sum of cost per call in one session
```

Prices are read live from the public OpenRouter price list. On 1 October 2026 GPT 4o mini cost 0.15 and 0.60 US dollars per million input and output tokens, and GPT 4o cost 2.50 and 10.00. A report of about 4,000 input and 1,500 output tokens on GPT 4o costs about 2.5 US cents. If a model's price cannot be found, the panel shows the tokens and says the price is not verified.

## LLM guardrail

The model only summarises and extracts. Both prompts forbid ratings, buy or sell advice and target prices. All charts, tables and scores come from data sources. The model only writes text summaries. `evals/eval_guardrail.py` tests this with 10 adversarial prompts.
