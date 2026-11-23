# Sources, formulas and comparison

## What was read

1. Wolfers, J. and Zitzewitz, E. (2004). "Prediction Markets". Journal of Economic Perspectives 18(2), 107-126. Read in the authors' copy.
2. Bürgi, C., Deng, W. and Whelan, K. "Makers and Takers: The Economics of the Kalshi Prediction Market". Read as George Washington University Center for Economic Research working paper 2026-001 (February 2026, text dated January 2026), and checked against CESifo working paper 12122 (2025). Section, equation and table numbers below are from the GWU version. The CEPR discussion paper 20631 named in the design is the same paper. I did not fetch that copy, so numbering there may differ.
3. The fee page of the Polymarket documentation (`docs.polymarket.com/trading/fees`), read on 2026-11-23.
4. The price-history page of the Polymarket documentation, read on 2026-11-23.

Not read at source:

- Kalshi's fee schedule. The site returned HTTP 429 to automated requests on every attempt. The fee formula below is from Bürgi, Deng and Whelan, a secondary source, and it describes the period up to April 2025.
- Brier (1950), Murphy (1973) and Cox (1958), for the Brier score, its partition, and logistic recalibration. These formulas are standard. They are checked here by algebraic identities in the tests, and no published value was reproduced from them.

## Formulas

Throughout, P is a price in dollars for a contract that pays $1, and Y is 1 if it pays and 0 if not.

### Outcome and win rate

Bürgi, Deng and Whelan, equation 1: Y_ij = 1 if outcome j of event i occurs, 0 otherwise. Their Figure 3 plots the mean of Y at each price against the price. `calibration.reliability` does the same in ten bins of 10 cents and reports the mean price and win rate in each.

### Mincer-Zarnowitz regression

Bürgi, Deng and Whelan, equation 3:

    Y_ij - P_ij = alpha + psi * P_ij + e_ij

Unbiased prices give alpha = psi = 0. They estimate it on Yes contracts only, since the No contract is a linear transformation of the Yes one, and cluster standard errors by event and by contract. `calibration.mincer_zarnowitz` is the same least squares fit. Each market appears once per horizon here, so only the event clustering is needed. Their tables report prices and alpha in cents. This project uses dollars, so their alpha of -1.736 is -0.0174 here. psi has no unit.

### Logistic recalibration

    P(Y = 1) = sigmoid( a + b * log( P / (1 - P) ) )

Calibrated prices give a = 0 and b = 1. A slope b above 1 means outcomes are more extreme than prices, which is the favourite-longshot bias. Fitted by Newton's method in `calibration.logistic_recalibration`. This is not in either source. It is added because a slope in log odds does not depend on which side of a market is called the priced side.

### Brier score and its partition

    BS = mean( (P - Y)^2 )

With bins k holding a share w_k of the markets, mean price Pbar_k and win rate Ybar_k, and overall win rate Ybar:

    reliability = sum_k w_k (Pbar_k - Ybar_k)^2
    resolution  = sum_k w_k (Ybar_k - Ybar)^2
    uncertainty = Ybar (1 - Ybar)
    within_bin  = sum_k w_k [ var_k(P) - 2 cov_k(P, Y) ]
    BS = reliability - resolution + uncertainty + within_bin

The first three terms are Murphy's partition, which is exact when every price in a bin is equal. The fourth is what binning unequal prices leaves over. A test checks that the four sum to the score to twelve decimals.

Baselines: always 0.5 scores 0.25. Always the base rate scores Ybar (1 - Ybar). Skill is 1 - BS / (Ybar (1 - Ybar)).

### Fees

Kalshi. Bürgi, Deng and Whelan, section 2: takers paid "$0.07P(1 - P)" per contract, "rounding the total up to the nearest cent", and makers paid nothing in their sample period. `fees.kalshi_taker_fee` implements the rounded order fee. The edge tables use the per-contract rate without rounding, 0.07 * P * (1 - P), scaled by the `fee_multiplier` field of the public series record (1 for 16,760 of 16,793 series, 0.5 for 19, 0 for 14). 163 series have a fee type that also charges makers. Maker fees are not modelled, since every trade here is a taker's.

Polymarket. Fee page: "fee = C x feeRate x p x (1 - p)", where C is the number of shares, charged to takers only. The published table gives a feeRate from 0 (geopolitics) to 0.05 (sports, finance, tech, elections, and others) by category. The edge tables use 0.05 for every market as an upper bound.

Return on a purchase. Bürgi, Deng and Whelan, equation 2, define the post-fee rate of return as (Y - P - C) / (P + C) with C the fee. This project reports the numerator, profit per contract in dollars, and separately the mean profit divided by the mean cost.

### Bootstrap

Intervals are percentile intervals from 2,000 resamples of events with replacement. An event is a Polymarket event id or a Kalshi event ticker. A resample is passed to each statistic as integer weights. A test checks that weights and repeated rows give the same answer.

## Data reach

How far back the public APIs reach was the open question in the design.

| Venue | Close year | Markets fetched | With any price history |
| --- | --- | --- | --- |
| Polymarket | 2022 | 28 | 3 |
| Polymarket | 2023 | 104 | 101 |
| Polymarket | 2024 | 1,862 | 1,862 |
| Polymarket | 2025 | 3,600 | 3,599 |
| Polymarket | 2026 | 3,006 | 2,968 |
| Kalshi | 2021 | 13 | 12 |
| Kalshi | 2022 | 19 | 18 |
| Kalshi | 2023 | 17 | 17 |
| Kalshi | 2024 | 59 | 56 |
| Kalshi | 2025 | 686 | 556 |
| Kalshi | 2026 | 2,457 | 2,134 |

For Kalshi "with any price history" means at least one day with a usable two-sided quote. All 3,251 returned candlesticks.

Probes made while building, each a handful of requests:

- Polymarket markets that ended in 2021 and early 2022 returned no price history at any spacing. A market that ended in September 2022 did.
- For a closed Polymarket market, `fidelity=1440` and `fidelity=720` returned points. `fidelity=60` and the default returned none. A `startTs` and `endTs` range covering ten months was rejected as too long.
- Gamma's `offset` paging stops near 2,000 rows. The `/markets/keyset` endpoint does not.
- Kalshi's `/historical/markets` ignored `max_close_ts` and accepted `series_ticker`. Its cutoff endpoint reported that markets settled before 2026-09-24 are served from the historical tier.
- Listing all settled Kalshi markets is not practical without a filter: 1,000 non-combination markets covered about five and a half hours of one day. This is why the sample is drawn by series.

## Comparison with the sources

### Wolfers and Zitzewitz (2004)

They make no numerical calibration claim that can be recomputed here. Two qualitative claims apply.

| Claim | Where | Here |
| --- | --- | --- |
| Market prices are useful forecasts and get better near the event | pp. 110-113, Figure 1 | Agrees. Prices beat the base rate at every horizon on both venues, and on a fixed set of markets the Brier score falls from 30 days to 1 day: 0.082 to 0.044 on Polymarket, 0.129 to 0.083 on Kalshi. |
| Longshots are overvalued, so markets "may perform poorly at predicting small probability events" | pp. 116-117 | Not found. Under 20 cents, seven days out, outcome minus price is +0.6c (-0.1 to 1.4) on Polymarket and +0.1c (-2.7 to 3.1) on Kalshi. |

### Bürgi, Deng and Whelan

Their sample: 46,282 Yes contracts in 12,403 events, 2021 to April 2025, last traded prices from registered API access, markets with at least $1,000 traded, final spread at most 20 cents, open at least 24 hours.

| Claim | Where | Theirs | Here (Kalshi) | Verdict |
| --- | --- | --- | --- | --- |
| psi, 1 day before close | Table 5 | 0.017 (se 0.006), n = 26,835 | 0.022 (-0.028 to 0.066), n = 1,606 | Same sign, not distinguishable from zero or from theirs |
| alpha, 1 day | Table 5 | -0.0145 (se 0.0018) | -0.009 (-0.033 to 0.018) | Same |
| psi, 7 days | Table 5 | 0.037 (se 0.010), n = 7,178 | 0.024 (-0.041 to 0.081), n = 791 | Same |
| alpha, 7 days | Table 5 | -0.0157 (se 0.0036) | -0.003 (-0.036 to 0.029) | Same |
| Contracts at 10c and under lose over 60% after fees | Section 3.3, Figure 5 | below -60% | Buying the priced side in the 0 to 10c bin at the ask, with the fee: -24% of cost at 7 days, -1.4c a contract (-3.9 to 1.4) | Not replicated. See the first difference below. |
| Small positive returns above 50c, significant above 70c | Section 3.3, Figure 5 | positive | Mixed signs across the five bins above 50c, one interval of fifteen above zero | Not replicated at this sample size |
| Prices get more accurate nearer the close | Section 3.2, Figure 4 (mean absolute error) | falls each day | Brier score on 195 fixed markets: 0.129, 0.095, 0.083 at 30, 7 and 1 days | Agrees |
| Economics psi | Table 8 | 0.034 (se 0.010) | calibration slope 1.26 (1.03 to 1.75), psi 0.067 (-0.040 to 0.153), n = 182 | Same sign |

The paper has no Polymarket results. Polymarket's estimates lean the other way from the paper's Kalshi ones: psi is negative at all three horizons and the calibration slope is below 1, significantly so at one day (0.90, 0.85 to 0.96).

### Why the Kalshi numbers may differ

1. Price. They use the last traded price, which a taker accepted. This project uses the midpoint of the closing bid and ask and requires both a bid of at least 1 cent and an ask of at most 99 cents. A contract last traded at 2 cents with no bid is in their sample and not in this one. Their largest losses are in exactly those contracts.
2. Sample size. 791 contracts in 283 events against 7,178 at seven days. The interval for psi here is about three times as wide as theirs.
3. Sampling. They take every qualifying contract. This project draws 600 of 16,793 series and at most 25 markets from each, which gives small series the same weight as large ones.
4. Period. Theirs ends in April 2025. 97% of this sample closed in 2025 or 2026, after sports markets and maker fees arrived.
5. Thresholds. Their floor is $1,000 traded and 24 hours open. This one is 100 contracts and two days.

## Choices fixed before the data

Fixed in `config.py` before any real result was computed: the seed, the horizons of 1, 7 and 30 days with 7 as the main one, the 36-hour staleness limit, the two-day minimum lifetime, the $100,000 Polymarket floor, 300 histories per month, 600 Kalshi series, 25 markets per series, the 100-contract floor, the 20-cent spread limit, ten equal price bins, and longshot and favourite thresholds of 20 and 80 cents.

## Variants tried

Counted in full. Nothing was tuned towards a result.

On simulated data, before any real result:

1. The clip applied to prices in the logistic fit was 0.005, then 0.0001. The first biased the slope upward on simulated fair markets with extreme prices.
2. The logistic fit was then restricted to prices from 1 to 99 cents with no clip. A single simulated upset at a tenth of a cent moved the slope more than thousands of ordinary markets did. Selecting on the price does not bias a model of the outcome given the price. This is the version used. It leaves out 1,178 of 4,588 Polymarket markets at seven days. The Mincer-Zarnowitz regression and every other table use all of them.
3. The simulated sample in the fast run went from 600 to 2,000 events per venue so that its intervals are tight enough to read.

After a dry run on a partial download, before the full results:

4. The Brier table gained a second sample, markets with a price at every horizon. The dry run showed the one-day rows scoring worse than the 30-day rows because they hold different markets.

After reading the full results:

5. A split of the bias by market type (yes or no against two named sides).
6. A split of the Polymarket bias by four volume tiers.

Splits 5 and 6 are in `results/splits.md` and are exploratory. No main table changed after the full results were read.

## Not verified

- Kalshi's current fee schedule, and whether 0.07 still applies to every series. The API fields `fee_type` and `fee_multiplier` are used as given.
- When Polymarket began charging fees, and what a given market paid at the time. The current table is applied to all years as an upper bound.
- What the Polymarket history price is: midpoint, last trade, or something else. The documentation does not say.
- Whether the $100,000 floor biases the Polymarket slope. This needs a sample with no floor and was not run.
- Whether the history endpoints return every point the venues hold. A market with an empty history is counted as having none.
- The category mapping. Polymarket tags and Kalshi series categories are folded into six groups by simple rules in `polymarket.py` and `kalshi.py`, and nothing checks them against a hand-labelled set.
