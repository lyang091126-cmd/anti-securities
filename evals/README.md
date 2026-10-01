# Evaluations

Two kinds of checks. Offline unit tests prove the scoring rules are coded correctly. Experiments on real data prove the scoring choices matter and that the fixes did what they claim.

## How to run

From the project root:

```bash
python evals/run_evals.py          # 18 offline tests, no network, about 5 seconds
python evals/eval_split_fix.py     # price convention experiment, needs internet, about 3 minutes
```

The guardrail eval needs an LLM key:

```powershell
$env:OPENROUTER_API_KEY = "sk-or-..."
python evals/eval_guardrail.py
```

## Offline unit tests — 18 of 18 pass

| File | What it checks |
|---|---|
| `test_scorecard.py` | Uses a fake stock with hand-made prices and calls, so every right answer is known in advance. Checks bullish and bearish hit rules, that calls younger than 252 trading days are not scored, that a zero target is dropped, that a target published before a 10 for 1 split is divided by 10, that a split before the call is not applied twice, that a market with no coverage returns an honest reason, the 12 month return after a buy rating, and the 8 call minimum for the firm league table |
| `test_llm_cost.py` | Key prefix routing, including the old bug where OpenRouter keys were sent to Zhipu. Cost arithmetic against hand calculation. An unknown model price returns None instead of a guess. The advice detector flags 8 real advice sentences and passes 4 refusals |
| `test_snapshot.py` | The cloud fallback. Rate limited data is replaced by the dated snapshot, healthy data is left alone, and a stock with no snapshot is never filled with another stock's data |

### Do the tests actually catch bugs?

A test suite that always passes proves little on its own. So four bugs were planted in `scorecard.py` on purpose, one at a time, and the suite was run against each:

| Planted bug | Caught by |
|---|---|
| Split adjustment removed | `test_split_adjustment` |
| Bullish hit rule broken | `test_hit_rules_and_pending`, `test_split_adjustment` |
| Pending calls scored anyway | `test_hit_rules_and_pending` |
| League table minimum removed | `test_firm_league_threshold` |

All four were caught.

## Experiment 1 — price convention, `eval_split_fix.py`

The scorecard compares a target that the analyst published years ago with a price 12 months later. Yahoo's default price history is adjusted for later splits and for dividends, but the stored targets are not. The experiment scores every stock three ways.

| Ticker | Splits in window | A: raw targets, dividend adjusted prices | B: split fixed targets | C: split fixed, prices not dividend adjusted (current) |
|---|---|---|---|---|
| NVDA | 2 | 16.5% | 73.9% | 74.2% |
| MSFT | 0 | 56.8% | 56.8% | 59.5% |
| AAPL | 1 | 32.5% | 50.7% | 49.6% |
| AMZN | 1 | 35.9% | 43.4% | 43.4% |
| GOOGL | 1 | 37.5% | 58.9% | 59.3% |
| META | 0 | 80.9% | 80.9% | 81.1% |
| TSLA | 2 | 23.4% | 32.3% | 32.3% |
| AVGO | 1 | 21.2% | 69.6% | 75.6% |
| AMD | 0 | 61.6% | 61.6% | 61.6% |
| JPM | 0 | 54.7% | 54.7% | 64.5% |

**Reading it.** The four stocks with no split in the window, MSFT, META, AMD and JPM, are a control group. Their scores are identical in A and B, which shows the split fix touches only stocks that really split. The six stocks that did split move up by 27.0 points on average. The dividend fix, B to C, works as a second natural experiment: JPM, a large dividend payer, moves from 54.7% to 64.5%, while AMD, AMZN and TSLA, which pay no dividend, do not move at all.

Raw output: `results/split_fix_eval.csv`.

## Experiment 2 — guardrail, `eval_guardrail.py`

The product promises that the model only restates facts and never gives a rating, a target or trading advice. The eval sends 10 prompts designed to break that promise, half of them with real analyst numbers attached as bait, using the same system prompt and model as the live report. Each answer goes through `llm_cost.contains_advice()`. The script also records real token counts and cost for every call.

Target: 10 of 10 answers with no advice. Results are written to `results/guardrail_<date>.json`.

## Critique of these evals

- **They test the code, not the analysts.** The unit tests prove the rules are applied correctly. They do not prove the rules are the best way to judge a forecast.
- **The real data sample is biased.** The 10 stocks are today's winners, so bullish calls look good and bearish calls look bad. See `data/README.md`. The next version should pick stocks without hindsight and compare returns with an index.
- **The advice detector is a word list.** It catches the common forms of advice in Chinese and English, and its own tests pass, but a model could still give advice in a form the list does not cover. Flagged answers should be read by a person, and the list should grow from real failures.
- **No test of the A-share path.** Yahoo has no A-share analyst calls, so that path is only tested for its "no coverage" message.
