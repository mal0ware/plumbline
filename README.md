# Plumbline

**When a prediction market says 70%, does it happen 70% of the time?**

> **Status: planned.** This repository holds the design. No results exist yet, and nothing below is a finding. Each box in the roadmap gets ticked when the code and its tests are in.

## The question

Prediction-market prices are read as probabilities. Are they? Where are they off, and is the gap bigger than what it costs to trade it?

## What this will contain

- A collector for settled markets from public APIs
- Calibration curves by category and by time to expiry
- The favourite-longshot bias, with confidence intervals
- Fees applied to every apparent gap
- Brier score against a naive baseline

## The result it is built to show

The calibration curve, and one sentence on whether any bias is larger than the fee.

Whatever the answer turns out to be goes at the top of this file, with one chart, before any installation step.

## Sources

- Wolfers and Zitzewitz, "Prediction Markets", Journal of Economic Perspectives 18(2), 2004
- Bürgi, Deng and Whelan, "Makers and Takers", CEPR discussion paper, 2026 (working paper)

Every number that differs from a source will be listed in `PAPER.md` with the likely reason.

## Data

Public market-data endpoints that need no key. How far back price history reaches through them is the first thing this project has to find out.

## How it is tested

The maths is tested before any result is trusted.

- A simulated market that is calibrated by construction comes out calibrated
- A planted longshot bias is recovered with the right sign and size
- No market is counted before it has settled

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

- [ ] Project skeleton, CI, and the reproduce command
- [ ] A collector for settled markets from public APIs
- [ ] Calibration curves by category and by time to expiry
- [ ] The favourite-longshot bias, with confidence intervals
- [ ] Fees applied to every apparent gap
- [ ] Brier score against a naive baseline
- [ ] `PAPER.md` comparison with the sources
- [ ] Results and limits written up at the top of this file

## Limits

- A miscalibrated price is not free money. Fees, spreads and thin books sit between the chart and a trade.
- Markets that never settled or were cancelled are a selection problem, and are reported separately.
- This reads public data only. It places no orders and needs no account.
- This is research code. It is not investment advice and it does not trade.

## The name

A plumb line tells you whether a wall is true. Calibration is the same test for a probability.

## Licence

MIT. See `LICENSE`.
