# Plumbline

**When a prediction market says 70%, does it happen 70% of the time?**

Close to it. Seven days before close, on 4,588 settled Polymarket markets and 791 settled Kalshi markets, the share that settled in favour stays within the 95% interval of the price in 19 of 20 price bins. There is no favourite-longshot bias in this sample: the calibration slope is 0.94 (0.87 to 1.01) on Polymarket and 1.04 (0.90 to 1.22) on Kalshi, where 1 is perfect and above 1 is the bias. No gap is reliably larger than the cost of trading it. After fees, and after the quoted spread on Kalshi, 4 of 120 bin-and-side tests have an interval above zero, and chance alone would give about 3.

![Share of markets that settled in favour, against the price seven days before close](results/calibration.png)

The Kalshi sample is too small to confirm or reject the bias that Bürgi, Deng and Whelan report there. The Polymarket sample keeps only markets with at least $100,000 traded, which is a selection on something known only at the end. Both points are covered under Limits.

## The question

Prediction-market prices are read as probabilities. Are they? Where are they off, and is the gap bigger than what it costs to trade it?

## Reproduce

```
uv sync
uv run python scripts/fetch_data.py
uv run python scripts/reproduce.py
```

The fetch makes about 14,000 requests and took 42 minutes here. It can be stopped and started again. `reproduce.py` then takes under a minute and rewrites every file in `results/`. Running it twice on the same download gives identical files.

`uv run python scripts/reproduce.py --fast` needs no data and no network. It simulates one fair venue and one with a planted bias, runs the same code on them, and writes to `results_fast/`. CI runs this.

A later fetch will not return exactly the same markets, so the numbers will move a little. The numbers here come from the fetch that finished at 20:08 UTC on 2026-11-23.

## What was built

- A collector for settled markets from two public APIs, with spaced requests, retries and a resumable cache (`collect.py`, `polymarket.py`, `kalshi.py`).
- One price per market at 1, 7 and 30 days before close, read without looking ahead (`observe.py`).
- Calibration curves, the Mincer-Zarnowitz regression, a logistic calibration slope, and the Brier score with its Murphy partition (`calibration.py`).
- Confidence intervals from a bootstrap that resamples whole events, because markets in one event share an outcome.
- Taker fees for both venues and the profit left in each price bin after them (`fees.py`).
- A simulator of markets that are calibrated by construction, with an optional planted bias (`simulate.py`).

## What was found

All intervals are 95%, from 2,000 bootstrap resamples of events. The seven-day horizon was chosen as the main one before any data was fetched.

### The favourite-longshot bias

| Venue | Days before close | Markets | Events | Mean of outcome minus price | Mincer-Zarnowitz slope | Calibration slope |
| --- | --- | --- | --- | --- | --- | --- |
| Polymarket | 1 | 8,415 | 6,323 | +1.1c (0.3 to 1.8) | -0.013 (-0.034 to 0.006) | 0.90 (0.85 to 0.96) |
| Polymarket | 7 | 4,588 | 3,129 | +1.0c (0.0 to 1.9) | -0.008 (-0.042 to 0.022) | 0.94 (0.87 to 1.01) |
| Polymarket | 30 | 2,036 | 1,177 | -1.1c (-2.3 to 0.1) | -0.047 (-0.095 to 0.004) | 0.95 (0.86 to 1.05) |
| Kalshi | 1 | 1,606 | 920 | 0.0c (-2.0 to 2.0) | 0.022 (-0.028 to 0.066) | 1.06 (0.96 to 1.17) |
| Kalshi | 7 | 791 | 283 | +0.7c (-2.2 to 3.3) | 0.024 (-0.041 to 0.081) | 1.04 (0.90 to 1.22) |
| Kalshi | 30 | 490 | 165 | -3.0c (-6.7 to 0.8) | 0.033 (-0.058 to 0.112) | 1.16 (0.96 to 1.48) |

A favourite-longshot bias would show as a Mincer-Zarnowitz slope above 0 and a calibration slope above 1. Polymarket shows neither. Where its slope differs from 1 it is below, which means prices slightly too extreme: at one day before close, and at seven days after a market opened (0.88, 0.81 to 0.95). That second moment is known in real time, so it does not depend on when the market happened to close. The effect is small and I would not lean on it, for the selection reason under Limits.

Kalshi's estimates all point the way the paper says, and none of the intervals excludes zero. They also include the paper's values. At seven days Bürgi, Deng and Whelan report a Mincer-Zarnowitz slope of 0.037 with a standard error of 0.010 from 7,178 contracts. This sample has 791 contracts in 283 events, and its interval is about three times as wide as the paper's, too wide to see an effect of that size.

Two splits were made after reading the table above, so treat them as exploratory (`results/splits.md`). On Polymarket the low slope sits in markets between two named sides, mostly sports matches: 0.68 (0.49 to 0.92) at seven days on 672 markets. Yes-or-no markets give 0.99 (0.91 to 1.08). Splitting by traded volume shows no steady pattern.

### Is any gap bigger than the fee?

For every price bin, horizon and side, `results/edge_after_costs.md` gives the mean profit per contract of buying and holding to settlement. On Kalshi the buyer pays the quoted ask (or one minus the bid for the other side) plus the taker fee of 0.07 x P x (1 - P). The median quoted spread was 4 cents. On Polymarket the history has one price and no spread, so the test uses that price plus the highest rate in the current fee table, 0.05 x p x (1 - p).

![Mean profit per contract after costs, by price bin, seven days before close](results/edge_after_costs.png)

Of 120 tests, 4 have an interval above zero:

| Venue | Days | Trade | Price bin | Markets | Profit per contract |
| --- | --- | --- | --- | --- | --- |
| Polymarket | 1 | buy the priced side | 10c to 20c | 532 | 3.2c (0.1 to 6.5) |
| Polymarket | 1 | buy the priced side | 20c to 30c | 604 | 4.3c (0.8 to 7.8) |
| Polymarket | 7 | buy the priced side | 20c to 30c | 354 | 5.2c (0.4 to 10.1) |
| Kalshi | 30 | buy the priced side | 80c to 90c | 31 | 10.5c (9.4 to 11.8) |

Each test has a 2.5% chance of landing above zero when nothing is there, so 3 of 120 are expected. The Kalshi row is 31 markets in 25 events that all happened to win. The three Polymarket rows are the same neighbouring bins at two horizons, with no spread charged, and they are the pattern the volume floor would produce by itself. I do not read any of the four as a tradeable gap.

### Brier score against a naive baseline

| Venue | Days before close | Markets | Brier score | Always the base rate | Always 50% | Skill against the base rate |
| --- | --- | --- | --- | --- | --- | --- |
| Polymarket | 1 | 8,415 | 0.134 | 0.224 | 0.25 | 40% (38 to 42) |
| Polymarket | 7 | 4,588 | 0.117 | 0.200 | 0.25 | 42% (39 to 44) |
| Polymarket | 30 | 2,036 | 0.082 | 0.157 | 0.25 | 48% (42 to 52) |
| Kalshi | 1 | 1,606 | 0.140 | 0.242 | 0.25 | 42% (37 to 46) |
| Kalshi | 7 | 791 | 0.117 | 0.241 | 0.25 | 52% (44 to 58) |
| Kalshi | 30 | 490 | 0.094 | 0.207 | 0.25 | 54% (43 to 63) |

Prices beat both baselines at every horizon. The base rate here is computed from the same outcomes it is scored on, which favours the baseline.

The rows above hold different markets, because only long-lived markets have a price 30 days out. That is why the score looks better further from the close. On the markets that have a price at all three horizons the order is the expected one:

| Venue | Markets | 30 days | 7 days | 1 day |
| --- | --- | --- | --- | --- |
| Polymarket | 2,010 | 0.082 | 0.053 | 0.044 |
| Kalshi | 195 | 0.129 | 0.095 | 0.083 |

![Brier score by horizon on the same markets](results/brier_by_horizon.png)

### By category

At seven days, by category (`results/by_category.md`). Categories with fewer than 100 markets are left out.

| Venue | Category | Markets | Brier score | Skill against the base rate | Calibration slope |
| --- | --- | --- | --- | --- | --- |
| Polymarket | sports | 1,960 | 0.171 | 25% | 0.87 (0.76 to 1.00) |
| Polymarket | politics | 1,610 | 0.071 | 58% | 0.97 (0.86 to 1.10) |
| Polymarket | crypto | 444 | 0.086 | 50% | 1.08 (0.87 to 1.39) |
| Polymarket | other | 220 | 0.099 | 55% | 0.88 (0.68 to 1.23) |
| Polymarket | culture | 187 | 0.096 | 48% | 1.02 (0.68 to 1.61) |
| Polymarket | economics | 167 | 0.054 | 64% | 1.14 (0.77 to 2.60) |
| Kalshi | culture | 274 | 0.139 | 42% | 0.89 (0.69 to 1.21) |
| Kalshi | economics | 182 | 0.101 | 59% | 1.26 (1.03 to 1.75) |
| Kalshi | politics | 159 | 0.110 | 53% | 0.94 (0.66 to 1.43) |
| Kalshi | sports | 130 | 0.111 | 48% | 1.25 (0.85 to 1.97) |

Sports on Polymarket has the least skill, which fits a category full of near even contests. Kalshi economics is the one category whose slope interval sits above 1. That is one of ten intervals and I would want more data before calling it a finding.

## Which markets have history

This was the first thing the design set out to learn. The answers shape everything above.

- Polymarket price history starts in late 2022. Of 28 sampled markets that closed in 2022, 3 returned any history. From 2023 on, 97% to 100% do. Markets from the earlier automated market maker are listed with outcomes but have no price series through the public API. The earliest price used is from 2022-12-23.
- For closed Polymarket markets the history endpoint returned points only at a spacing of 12 hours or coarser. A request for hourly points came back empty. So markets that live less than two days cannot be measured, and they are a large group: 45,706 of 110,315 settled markets above the volume floor, 41%, were open for under two days. Most are single sports games and short crypto contracts. Nothing here says anything about them.
- The Polymarket documentation does not say whether the history price is a midpoint or a last trade. There is no bid or ask in it.
- Kalshi lists settled markets back to 2021 and serves daily candlesticks with bid and ask for all of them. Every one of the 3,251 sampled markets returned candlesticks.
- Kalshi quotes are often one-sided. 458 of 3,251 sampled markets never had a bid of at least 1 cent and an ask of at most 99 cents within 20 cents of each other on any day. Only 24% gave a usable price seven days before close, counting the ones that were not open yet.
- Markets that did not settle to one side are counted and left out: 275 of 110,590 on Polymarket (splits and voids), and 979 of 84,003 on Kalshi (scalar results).

The full counts are in `results/sample_funnel.md`, `results/history_reach.md` and `results/coverage.md`.

## Sources

- Wolfers and Zitzewitz, "Prediction Markets", Journal of Economic Perspectives 18(2), 2004.
- Bürgi, Deng and Whelan, "Makers and Takers: The Economics of the Kalshi Prediction Market". I read the George Washington University working paper 2026-001 (February 2026) and the CESifo working paper 12122. The CEPR discussion paper 20631 is the same paper and I did not fetch that copy.

`PAPER.md` has the formulas with their locations in the sources, the comparison claim by claim, and every variant tried.

## Data

Everything comes from public endpoints that need no key and no account. The fetch sends a generic User-Agent and nothing else. Nothing in `data/` is committed.

Polymarket:

- `GET https://gamma-api.polymarket.com/markets/keyset` for closed markets with at least $100,000 traded and a scheduled end from 2022-10-01 to 2026-10-31. This listed 110,590 markets.
- `GET https://clob.polymarket.com/prices-history` with `interval=max` and `fidelity=720` for 8,600 of them: up to 300 drawn at random per month of close, from markets open at least two days. Their closes run from 2022-06-02 to 2026-11-01.

Kalshi, all under `https://api.elections.kalshi.com/trade-api/v2`:

- `GET /series` for the 16,793 series. 600 were drawn at random.
- `GET /historical/markets` and `GET /markets?status=settled` for the settled markets of those series that closed before 2026-11-01. 351 of the 600 had any, 84,003 markets in all.
- `GET /historical/markets/{ticker}/candlesticks` and `GET /series/{series}/markets/{ticker}/candlesticks`, daily, for 3,251 markets: up to 25 drawn per series from binary markets with at least 100 contracts traded and open at least two days. Their closes run from 2021-09-06 to 2026-10-31.

Skipped:

- Manifold. It is play money, so fees and trading costs do not apply, and I left it out to keep to two venues.
- Trade-level data on either venue. The paper used Kalshi trades obtained with a registered account. This project uses only what is served without one.
- Kalshi's fee schedule PDF. The site answered automated requests with HTTP 429, so the fee formula is taken from the paper and from the fee fields in the public series record.

Requests were spaced 0.2 seconds apart for Polymarket and 0.5 seconds for Kalshi. Requests that hit a rate limit or a server error are retried with backoff, and none failed after retries. Both venues publish their data under their own terms of use. Read them before using the data for anything else.

## How it is tested

The maths is tested before any result is trusted. 83 tests, none of which touch the network.

- A simulated market that is calibrated by construction comes out calibrated.
- A planted longshot bias is recovered with the right sign and size.
- No market is counted before it has settled, and a split or void market is never scored.
- A quote from after the chosen moment never changes an observation.
- The Brier partition sums to the Brier score exactly, and fee formulas match worked values.
- A bootstrap that ignores events is too narrow by the factor theory says, and the one used here is not.
- `reproduce.py --fast` run twice gives identical files.

```
uv run pytest
uv run ruff check .
uv run mypy src
```

## Layout

```
src/plumbline/      the code
tests/             maths tests first
scripts/reproduce.py   one command rebuilds every figure and table
scripts/fetch_data.py  downloads public data into data/ (never committed)
results/           committed figures and small tables
PAPER.md           citations, claims tested, comparison with the sources
```

## Roadmap

- [x] Project skeleton, CI, and the reproduce command
- [x] A collector for settled markets from public APIs
- [x] Calibration curves by category and by time to expiry
- [x] The favourite-longshot bias, with confidence intervals
- [x] Fees applied to every apparent gap
- [x] Brier score against a naive baseline
- [x] `PAPER.md` comparison with the sources
- [x] Results and limits written up at the top of this file

The original plan was a collector that records prices for weeks. This build uses the history the public APIs already serve.

## Limits

- The Polymarket sample keeps markets with at least $100,000 traded. Total volume is known only at the end, and a longshot that comes in draws more trading than one that fades. That would put extra winning longshots in the sample and push the slope below 1, which is the direction found. I did not test this. Doing so needs a sample with no floor.
- The Kalshi sample is small where it counts: 791 markets in 283 events at seven days. It can rule out a large bias and cannot see one the size the paper reports.
- The Kalshi sample is drawn by series, with at most 25 markets from each. It weights a series with 30 markets the same as one with 4,000, so it is not a picture of Kalshi's volume.
- Requiring a two-sided Kalshi quote drops the cheapest contracts, those bid below one cent. The paper finds its largest losses in contracts under 10 cents, so this filter removes part of where the bias would be.
- "Days before close" is measured from a close that may have come early. A market that settles early on an event is sampled in the days just before that event. Seven days after open does not have this problem and is reported next to it.
- One day before close, 31% of Polymarket prices were already within 2 cents of 0 or 1. Some of those outcomes were known and waiting for settlement. They make the one-day rows look better calibrated at the extremes than a forecast would be.
- Polymarket has no spread in its history, so its costs are understated. Its fees are the current published table applied to all years. I could not find when fees began, and most of the sample period may have had none.
- The Kalshi fee is the large-order rate. A small order pays more because the total is rounded up to a cent.
- Several hundred intervals are reported across the tables. A few will exclude zero by chance.
- Both samples are mostly 2025 and 2026, because that is when most markets were listed.
- A miscalibrated price is not free money. Fees, spreads and thin books sit between the chart and a trade.
- This reads public data only. It places no orders and needs no account.
- This is research code. It is not investment advice and it does not trade.

## The name

A plumb line tells you whether a wall is true. Calibration is the same test for a probability.

## Licence

MIT. See `LICENSE`.
