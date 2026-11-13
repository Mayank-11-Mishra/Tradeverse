# Indicator renderer and settings audit

This table covers every implemented calculation engine (not the unimplemented proprietary study inventory). Each engine exposes all registered numeric inputs plus line color, line width, visibility and timeframe visibility. Each result is fetched from cached broker candles; no fabricated prices.

| Indicator | Pane | Inputs | Style & visibility |
|---|---|---|---|
| ad_line | Separate oscillator | None | Color, width, show/hide, timeframes |
| adx | Separate oscillator | length=14 | Color, width, show/hide, timeframes |
| aroon | Separate oscillator | length=14 | Color, width, show/hide, timeframes |
| atr | Separate oscillator | length=14 | Color, width, show/hide, timeframes |
| awesome | Separate oscillator | fast=5, slow=34 | Color, width, show/hide, timeframes |
| bbands | Price overlay | length=20, mult=2.0 | Color, width, show/hide, timeframes |
| bbwidth | Separate oscillator | length=20, mult=2.0 | Color, width, show/hide, timeframes |
| cci | Separate oscillator | length=20 | Color, width, show/hide, timeframes |
| chaikin_osc | Separate oscillator | fast=3, slow=10 | Color, width, show/hide, timeframes |
| choppiness | Separate oscillator | length=14 | Color, width, show/hide, timeframes |
| cmf | Separate oscillator | length=20 | Color, width, show/hide, timeframes |
| cmo | Separate oscillator | length=14 | Color, width, show/hide, timeframes |
| dema | Price overlay | length=20 | Color, width, show/hide, timeframes |
| donchian | Price overlay | length=20 | Color, width, show/hide, timeframes |
| dpo | Separate oscillator | length=20 | Color, width, show/hide, timeframes |
| ema | Price overlay | length=20 | Color, width, show/hide, timeframes |
| fisher | Separate oscillator | length=10 | Color, width, show/hide, timeframes |
| force | Separate oscillator | length=13 | Color, width, show/hide, timeframes |
| hull | Price overlay | length=20 | Color, width, show/hide, timeframes |
| ichimoku | Price overlay | tenkan=9, kijun=26, senkou_b=52 | Color, width, show/hide, timeframes |
| keltner | Price overlay | length=20, atr_n=10, mult=2.0 | Color, width, show/hide, timeframes |
| linreg | Price overlay | length=20 | Color, width, show/hide, timeframes |
| ma_ribbon | Price overlay | start=10, step=5, count=8 | Color, width, show/hide, timeframes |
| macd | Separate oscillator | fast=12, slow=26, signal=9 | Color, width, show/hide, timeframes |
| mfi | Separate oscillator | length=14 | Color, width, show/hide, timeframes |
| momentum | Separate oscillator | length=10 | Color, width, show/hide, timeframes |
| natr | Separate oscillator | length=14 | Color, width, show/hide, timeframes |
| nvi_pvi | Separate oscillator | None | Color, width, show/hide, timeframes |
| obv | Separate oscillator | None | Color, width, show/hide, timeframes |
| price_lines | Price overlay | None | Color, width, show/hide, timeframes |
| psar | Price overlay | step=0.02, max_step=0.2 | Color, width, show/hide, timeframes |
| pvt | Separate oscillator | None | Color, width, show/hide, timeframes |
| roc | Separate oscillator | length=12 | Color, width, show/hide, timeframes |
| rsi | Separate oscillator | length=14 | Color, width, show/hide, timeframes |
| sma | Price overlay | length=20 | Color, width, show/hide, timeframes |
| stddev | Separate oscillator | length=20 | Color, width, show/hide, timeframes |
| stoch | Separate oscillator | k=14, d=3, smooth=1 | Color, width, show/hide, timeframes |
| stochrsi | Separate oscillator | rsi_n=14, stoch_n=14, k=3, d=3 | Color, width, show/hide, timeframes |
| supertrend | Price overlay | period=10, mult=3.0 | Color, width, show/hide, timeframes |
| tema | Price overlay | length=20 | Color, width, show/hide, timeframes |
| trima | Price overlay | length=20 | Color, width, show/hide, timeframes |
| tsi | Separate oscillator | long=25, short=13 | Color, width, show/hide, timeframes |
| ultimate | Separate oscillator | short=7, medium=14, long=28 | Color, width, show/hide, timeframes |
| variance | Separate oscillator | length=20 | Color, width, show/hide, timeframes |
| volume_oscillator | Separate oscillator | fast=12, slow=26 | Color, width, show/hide, timeframes |
| vwap | Price overlay | None | Color, width, show/hide, timeframes |
| vwma | Price overlay | length=20 | Color, width, show/hide, timeframes |
| willr | Separate oscillator | length=14 | Color, width, show/hide, timeframes |
| wma | Price overlay | length=20 | Color, width, show/hide, timeframes |
| zlema | Price overlay | length=20 | Color, width, show/hide, timeframes |
| zscore | Separate oscillator | length=20 | Color, width, show/hide, timeframes |

**Limitations:** Multiple lines use the same selected color by design. Some indicator outputs (e.g., Ichimoku displacement) are rendered at the timestamps returned by the calculation engine rather than reproducing each vendor-specific shifting convention. Saved layout data is preserved. Renko and P&F currently show transformed price data without studies. A hidden indicator remains in the saved layout and can be re-enabled. Fully tick-updated study calculations require streaming indicator evaluation in the backend; current study plots are based on the latest cached historical candle series.
