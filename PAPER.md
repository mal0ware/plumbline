# Sources, formulas and comparison

## What was read

1. Wolfers, J. and Zitzewitz, E. (2004). "Prediction Markets". Journal of Economic Perspectives 18(2), 107-126. Read in the authors' copy.
2. Bürgi, C., Deng, W. and Whelan, K. "Makers and Takers: The Economics of the Kalshi Prediction Market". Read as George Washington University Center for Economic Research working paper 2026-001 (February 2026, text dated January 2026), and checked against CESifo working paper 12122 (2025). Section, equation and table numbers below are from the GWU version. The CEPR discussion paper 20631 is the same paper. I did not fetch that copy, so numbering there may differ.
3. The fee page of the Polymarket documentation (`docs.polymarket.com/trading/fees`), read on 2026-11-23.
4. The price-history page of the Polymarket documentation, read on 2026-11-23.

Not read at source:

- Kalshi's fee schedule. The site returned HTTP 429 to automated requests on every attempt. The fee formula below is from Bürgi, Deng and Whelan, a secondary source, and it describes the period up to April 2025.
- Brier (1950), Murphy (1973) and Cox (1958), for the Brier score, its partition, and logistic recalibration. Wilson (1927) for the score interval, Kish (1965) for the design effect, Holm (1979) for the step-down correction. These formulas are standard. They are checked here by algebraic identities, worked values and simulation in the tests, and no published value was reproduced from them.

## Formulas

Throughout, P is a price in dollars for a contract that pays $1, and Y is 1 if it pays and 0 if not.

### Outcome and win rate

Bürgi, Deng and Whelan, equation 1: Y_ij = 1 if outcome j of event i occurs, 0 otherwise. Their Figure 3 plots the mean of Y at each price against the price. `calibration.reliability` does the same in price bins and reports the mean price and win rate in each.

### Live prices

A price from 5 to 95 cents is called live. Each table is computed on live prices and on all prices. On live prices the bins are 5 to 10 cents, eight bins of 10 cents, and 90 to 95 cents. On all prices they are ten bins of 10 cents.

The reason is in `results/extremes.md`. Seven days before close, 43% of the first Polymarket sample is outside 5 to 95 cents and 34% is within 2 cents of 0 or 1. Those rows win at almost exactly their price, and there are enough of them to dominate a mean gap, a Mincer-Zarnowitz slope or a Brier score. Conditioning on the price does not bias a statement about the outcome given the price.

### Mincer-Zarnowitz regression

Bürgi, Deng and Whelan, equation 3:

    Y_ij - P_ij = alpha + psi * P_ij + e_ij

Unbiased prices give alpha = psi = 0. They estimate it on Yes contracts only, since the No contract is a linear transformation of the Yes one, and cluster standard errors by event and by contract. `calibration.mincer_zarnowitz` is the same least squares fit. Their tables report prices and alpha in cents. This project uses dollars, so their alpha of -1.736 is -0.0174 here. psi has no unit.

### Logistic recalibration

    P(Y = 1) = sigmoid( a + b * log( P / (1 - P) ) )

Calibrated prices give a = 0 and b = 1. A slope b above 1 means outcomes are more extreme than prices, which is the favourite-longshot bias. Fitted by Newton's method in `calibration.logistic_recalibration`. This is not in either source. It is added because a slope in log odds does not depend on which side of a market is called the priced side. On all prices the fit uses prices from 1 to 99 cents. On live prices it uses every row.

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

Kalshi. Bürgi, Deng and Whelan, section 2: takers paid "$0.07P(1 - P)" per contract, "rounding the total up to the nearest cent", and makers paid nothing in their sample period. `fees.kalshi_taker_fee` implements the rounded order fee. The edge tables use the per-contract rate without rounding, 0.07 * P * (1 - P), scaled by the `fee_multiplier` field of the public series record (1 for 16,760 of 16,793 series, 0.5 for 19, 0 for 14). 163 series have a fee type that also charges makers (`results/kalshi_fee_terms.md`). Maker fees are not modelled, since every trade here is a taker's.

Polymarket. Fee page: "fee = C x feeRate x p x (1 - p)", where C is the number of shares, charged to takers only. The published table gives a feeRate from 0 (geopolitics) to 0.05 (sports, finance, tech, elections, and others) by category. The edge tables use 0.05 for every market as an upper bound.

Return on a purchase. Bürgi, Deng and Whelan, equation 2, define the post-fee rate of return as (Y - P - C) / (P + C) with C the fee. This project reports the numerator, profit per contract in dollars, and separately the mean profit divided by the mean cost.

### Bootstrap

Intervals for slopes, gaps and scores are percentile intervals from 2,000 resamples of clusters with replacement. A resample is passed to each statistic as integer weights. A test checks that weights and repeated rows give the same answer.

The cluster is the Polymarket event id. On Kalshi it is the series, because the sample was drawn by series and markets of one series share a subject. The first version resampled Kalshi event tickers. `results/clustering.md` gives both.

### Interval for a win rate in one bin

With w wins among n markets in G clusters, rate r = w / n, and cluster totals w_c and n_c:

    V      = G / (G - 1) * sum_c (w_c - r n_c)^2 / n^2     cluster-robust variance of r
    deff   = max( 1, V / ( r (1 - r) / n ) )               design effect
    n_eff  = n / deff
    centre = ( r + z^2 / (2 n_eff) ) / ( 1 + z^2 / n_eff )
    half   = z * sqrt( r (1 - r) / n_eff + z^2 / (4 n_eff^2) ) / ( 1 + z^2 / n_eff )

with z = 1.96. When every market won or every market lost, V is zero and says nothing about clustering, so n_eff = G: each cluster counts once. With one cluster n_eff = 1. This is `calibration.cluster_wilson`.

The first version used the cluster bootstrap here too. A bootstrap of a bin where all 31 markets won returns 31 of 31 on every resample, an interval of no width, and that produced a false hit in the cost tests. The Wilson interval for 31 of 31 in 25 events runs from 0.867 to 1.

The calibration curve reports the Wilson interval minus the mean price in the bin. The cost tests report it minus the mean cost. Prices and costs are treated as fixed.

### The null for the cost tests

A test is one price bin at one horizon on one venue, bought on one side. It counts as a hit when the interval of the mean profit after costs is above zero. There are 120 on each price sample.

The first version said each test has a 2.5% chance of a hit under no effect. That is wrong. A calibrated market loses the fee and the spread on average, so its chance is lower. The tests are also dependent: each bin is tested from both sides, and one market appears at up to three horizons.

`experiments.edge_tables` simulates the null. For each cluster it draws one uniform number U. A row with price p wins when U < p, at every horizon. Each row is then calibrated at its own price (the midpoint on Kalshi), rows of one cluster are as positively dependent as calibrated prices allow, and a market's outcomes at different horizons move together. Costs are the real ones. Each of 10,000 simulations goes through the same code as the data, with the same Wilson interval. A second version draws U per market, which leaves markets of one cluster independent.

From the simulations:

- `p_null` for a test is the share of simulations whose mean profit is at least the observed one.
- `p_holm` is the Holm adjustment of `p_null` over the 120 tests of a price sample. Holm is valid under any dependence.
- `results/edge_null.md` gives the mean number of hits per simulation and the share of simulations with at least as many hits as the data.

On live prices: 3 hits, 0.82 expected (0.69 with independent markets), at least 3 in 5.4% of simulations (3.2%), smallest `p_holm` 0.32.

### The volume floor

`experiments.floor_table` computes the bias on the no-floor sample under floors of $0, $1,000, $10,000 and $100,000 applied to final volume, and in the tiers between them. `experiments.floor_test_table` gives two differences in slope with bootstrap intervals. The first is the sample drawn above the floor minus the sample drawn with no floor, with an independent bootstrap for each. The second is inside the no-floor sample, markets that ended at or above $100,000 minus those that ended below, with one bootstrap that recomputes both.

## Data reach

| Venue | Close year | Markets fetched | With any price history |
| --- | --- | --- | --- |
| Polymarket, at least $100,000 | 2022 | 28 | 3 |
| Polymarket, at least $100,000 | 2023 | 104 | 101 |
| Polymarket, at least $100,000 | 2024 | 1,862 | 1,862 |
| Polymarket, at least $100,000 | 2025 | 3,600 | 3,599 |
| Polymarket, at least $100,000 | 2026 | 3,006 | 2,968 |
| Polymarket, no floor | 2022 | 13 | 0 |
| Polymarket, no floor | 2023 | 322 | 315 |
| Polymarket, no floor | 2024 | 1,415 | 1,414 |
| Polymarket, no floor | 2025 | 3,558 | 3,558 |
| Polymarket, no floor | 2026 | 3,300 | 3,268 |
| Kalshi | 2021 | 24 | 23 |
| Kalshi | 2022 | 79 | 76 |
| Kalshi | 2023 | 94 | 80 |
| Kalshi | 2024 | 265 | 254 |
| Kalshi | 2025 | 2,712 | 2,284 |
| Kalshi | 2026 | 10,050 | 8,491 |

For Kalshi "with any price history" means at least one day with a usable two-sided quote. All 13,224 returned candlesticks.

Probes made while building, each a handful of requests:

- Polymarket markets that ended in 2021 and early 2022 returned no price history at any spacing. A market that ended in September 2022 did.
- For a closed Polymarket market, `fidelity=1440` and `fidelity=720` returned points. `fidelity=60` and the default returned none. A `startTs` and `endTs` range covering ten months was rejected as too long.
- Gamma's `offset` paging stops near 2,000 rows. The `/markets/keyset` endpoint does not. It returns at most 100 rows a page and accepts `start_date_max`.
- With no volume filter, one day in June 2025 listed 159 closed markets and one day in June 2026 listed 8,402. At 100 rows a page, listing every day of 2026 would have taken tens of thousands of requests, which is why the no-floor sample lists six days a month.
- Kalshi's `/historical/markets` ignored `max_close_ts` and accepted `series_ticker`. Its cutoff endpoint reported that markets settled before 2026-09-24 are served from the historical tier.
- Listing all settled Kalshi markets is not practical without a filter: 1,000 non-combination markets covered about five and a half hours of one day. This is why the sample is drawn by series.

## Comparison with the sources

### Wolfers and Zitzewitz (2004)

They make no numerical calibration claim that can be recomputed here. Two qualitative claims apply.

| Claim | Where | Here |
| --- | --- | --- |
| Market prices are useful forecasts and get better near the event | pp. 110-113, Figure 1 | Agrees. Prices beat the base rate at every horizon on both venues, on live prices too, and on a fixed set of markets the Brier score falls from 30 days to 1 day: 0.082 to 0.044 on Polymarket, 0.158 to 0.101 on Kalshi. |
| Longshots are overvalued, so markets "may perform poorly at predicting small probability events" | pp. 116-117 | Not found at the low end. Under 20 cents, seven days out, live prices, outcome minus price is -0.4c (-2.7 to 2.1) on Kalshi and +2.1c (-0.3 to 4.6) in the high-volume Polymarket sample. The Kalshi bias found here is in the favourites. |

### Bürgi, Deng and Whelan

Their sample: 46,282 Yes contracts in 12,403 events, 2021 to April 2025, last traded prices from registered API access, markets with at least $1,000 traded, final spread at most 20 cents, open at least 24 hours. They use all prices, so the comparison is with the all-price rows here.

| Claim | Where | Theirs | Here (Kalshi, all prices) | Verdict |
| --- | --- | --- | --- | --- |
| psi, 1 day before close | Table 5 | 0.017 (se 0.006), n = 26,835 | 0.019 (-0.006 to 0.040), n = 6,210 | Same size. The interval includes zero. |
| alpha, 1 day | Table 5 | -0.0145 (se 0.0018) | -0.002 (-0.014 to 0.012) | Smaller here. Their value is just outside the interval. |
| psi, 7 days | Table 5 | 0.037 (se 0.010), n = 7,178 | 0.035 (0.004 to 0.065), n = 3,705 | Replicated |
| alpha, 7 days | Table 5 | -0.0157 (se 0.0036) | -0.003 (-0.020 to 0.015) | Smaller here. Their value is inside the interval. |
| Contracts at 10c and under lose over 60% after fees | Section 3.3, Figure 5 | below -60% | Buying the priced side in the 0 to 10c bin at the ask, with the fee: -42% of cost at 7 days, -2.5c a contract (-3.7 to -0.9) | Same sign, smaller. See the first difference below. |
| Small positive returns above 50c, significant above 70c | Section 3.3, Figure 5 | positive | Before costs, the 80 to 90c bin wins 5.7 points more than its price at 7 days (1.5 to 8.7). After the ask and the fee it makes 1.8c (-2.3 to 4.8). | Same sign before costs. Not distinguishable from zero after them. |
| Prices get more accurate nearer the close | Section 3.2, Figure 4 (mean absolute error) | falls each day | Brier score on 991 fixed markets: 0.158, 0.122, 0.101 at 30, 7 and 1 days | Agrees |
| Economics psi | Table 8 | 0.034 (se 0.010) | calibration slope 1.18 (1.01 to 1.41), n = 718 | Same sign |

On live prices the seven-day psi is 0.037 (-0.009 to 0.081) on 2,798 markets. The estimate is the same and the interval is wider, because the rows near 0 and 1 that were dropped carry most of the spread in price.

The first version of this study had 791 Kalshi markets at seven days and reported the paper's value as inside an interval too wide to test it. With 3,705 the interval excludes zero.

The paper has no Polymarket results. In the high-volume Polymarket sample the estimates lean the other way: on live prices psi is negative at all three horizons and the calibration slope is 0.88 (0.82 to 0.95) at one day and 0.90 (0.82 to 0.98) at seven. In the sample with no volume floor the seven-day slope is 1.00 (0.88 to 1.13).

### Why the Kalshi numbers may still differ

1. Price. They use the last traded price, which a taker accepted. This project uses the midpoint of the closing bid and ask and requires both a bid of at least 1 cent and an ask of at most 99 cents. A contract last traded at 2 cents with no bid is in their sample and not in this one. Their largest losses are in those contracts, and their alpha is more negative.
2. Sampling. They take every qualifying contract. This project draws 2,400 of 16,793 series and at most 25 markets from each, which gives small series the same weight as large ones.
3. Period. Theirs ends in April 2025. More than 96% of this sample closed in 2025 or 2026, after sports markets and maker fees arrived.
4. Thresholds. Their floor is $1,000 traded and 24 hours open. This one is 100 contracts and two days.
5. Size. 3,705 contracts in 738 series against 7,178 at seven days. The interval for psi here is about one and a half times as wide as theirs.

## What was chosen, and when

Git history shows the order of commits and nothing finer. `config.py` with the first list below was committed on 2026-11-23, before the commit that added the first results.

In that first code commit: the seed, the horizons of 1, 7 and 30 days with 7 as the main one, the 36-hour staleness limit, the two-day minimum lifetime, the $100,000 Polymarket floor, 300 histories per month, 600 Kalshi series, 25 markets per series, the 100-contract floor, the 20-cent spread limit, ten equal price bins, and longshot and favourite thresholds of 20 and 80 cents.

After the first results had been read, and after an outside review of them (2026-11-24). All of these are post hoc:

- The live-price subset, with bounds of 5 and 95 cents, as the main sample. The bounds are the ones the review named. No others were tried.
- The Wilson interval for a win rate in a bin, in place of the bootstrap.
- The simulated null for the cost tests and the Holm correction.
- Kalshi series as the bootstrap cluster.
- 1,800 more Kalshi series, drawn from those the first 600 left out. Because the first results had shown the Kalshi sample to be too small, this is an enlargement decided on seeing the data. The draw is seeded and the first 600 series and their markets are unchanged.
- The Polymarket sample with no volume floor: six days a month from January 2023, 300 histories per month of close. The start is 2023 because almost no market that closed in 2022 has a price history.
- The floors of $1,000 and $10,000 applied to the no-floor sample, and the column for prices at exactly 50 cents. The second was added after seeing that markets under $1,000 had a mean gap of -17.5 cents.

## Variants tried

Counted in full. Nothing was tuned towards a result.

On simulated data, while building. These three happened before the first code commit, so the history cannot confirm their order:

1. The clip applied to prices in the logistic fit was 0.005, then 0.0001. The first biased the slope upward on simulated fair markets with extreme prices.
2. The logistic fit was then restricted to prices from 1 to 99 cents with no clip. A single simulated upset at a tenth of a cent moved the slope more than thousands of ordinary markets did. This is the version used on all prices.
3. The simulated sample in the fast run went from 600 to 2,000 events per venue so that its intervals are tight enough to read.

After a dry run on a partial download:

4. The Brier table gained a second sample, markets with a price at every horizon. The dry run showed the one-day rows scoring worse than the 30-day rows because they hold different markets.

After reading the first full results:

5. A split of the bias by market type (yes or no against two named sides).
6. A split of the Polymarket bias by four volume tiers.

After the review:

7. Every item in the post hoc list above. Each was run once as described. The live bounds, the floors, the number of days listed and the number of added series were not varied.
8. While the second Kalshi fetch was listing series, I found that adding series would have changed which 25 markets were drawn from each of the first 600, because the per-series seed depended on the series' position in the list. I stopped the fetch, made the first 600 keep their original seeds, and started it again. No candlestick had been fetched under the wrong draw, and a test now checks that the first draw is unchanged.

Splits 5 and 6 are in `results/splits.md` and are exploratory.

## Not verified

- Kalshi's current fee schedule, and whether 0.07 still applies to every series. The API fields `fee_type` and `fee_multiplier` are used as given.
- When Polymarket began charging fees, and what a given market paid at the time. The current table is applied to all years as an upper bound.
- What the Polymarket history price is: midpoint, last trade, or something else. The documentation does not say. For markets that barely traded it is often exactly 50 cents and is far from the win rate.
- Whether the lower slope in high-volume Polymarket markets is selection on final volume or a real difference in how busy markets are priced. A floor on volume in a market's first days would separate the two. The public listing has only the final figure.
- Whether the history endpoints return every point the venues hold. A market with an empty history is counted as having none.
- Whether the `start_date_max` filter of the Polymarket listing drops markets that have no start date. The first sample falls back to the creation date for those, and the no-floor listing cannot.
- The category mapping. Polymarket tags and Kalshi series categories are folded into six groups by simple rules in `polymarket.py` and `kalshi.py`, and nothing checks them against a hand-labelled set.
- The paper's numbers as quoted here were read from the working paper. I did not rerun anything on their data.
