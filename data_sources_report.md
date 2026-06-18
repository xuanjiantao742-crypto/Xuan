# data_sources_report.md

生成时间：2026-06-19
阶段：第一阶段——数据来源和补充检查报告
状态：已完成公开来源核查；未开始全量回测。

---

# 公开来源核查摘要

## 1. BTCUSDT USDT-M 永续

### 1.1 Binance Vision / Binance Public Data

来源：

- https://data.binance.vision/
- https://github.com/binance/binance-public-data

核查结果：

- Binance Public Data 说明 Binance Data Collection 提供公开市场数据，并按 daily / monthly 文件组织。
- 该说明明确包含 Futures，并区分 USD-M Futures 与 COIN-M Futures。
- Futures `klines` 数据对应 `/fapi/v1/klines`，字段包含 open/high/low/close/volume/quote volume/number of trades/taker buy base/quote volume。
- Futures `aggTrades` 数据对应 `/fapi/v1/aggTrades` 或 `/dapi/v1/aggTrades`。
- Futures `trades` 数据对应 `/fapi/v1/trades`。
- 公共文件带 `.CHECKSUM`，下载后必须校验。

本研究用途：

- BTCUSDT USDT-M 永续 1m K 线：主数据。
- aggTrades：BTC 剥头皮和逐笔 CVD 首选。
- trades：更细但更大，作为扩展。
- K 线内 taker buy volume：只能做 K 线级近似 CVD。

限制：

- 当前阶段尚未枚举目录，不能确认实际首月/末月。
- REST `aggTrades` 文档显示查询窗口受限，不适合直接拉多年历史；多年数据应走 Binance Vision 文件。
- 不能用 Binance Spot 数据替代 USDT-M 永续。

### 1.2 Binance 官方 REST：K 线

来源：

- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data

核查结果：

- USD-M Futures K 线接口为 `GET /fapi/v1/klines`。
- K 线以 open time 唯一标识。
- 返回字段包含 OHLC、volume、close time、quote volume、number of trades、taker buy base/quote volume。
- 单次 limit 最大 1500。

本研究用途：

- 可用于补缺、抽样校验、近端数据更新。
- 全量历史更适合走 Binance Vision 文件。

### 1.3 Binance 官方 REST：funding rate

来源：

- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History

核查结果：

- 接口为 `GET /fapi/v1/fundingRate`。
- 支持 `symbol / startTime / endTime / limit`。
- 返回 `symbol / fundingRate / fundingTime / markPrice`。
- limit 最大 1000，按时间升序返回。

本研究用途：

- BTC 永续真实 PnL 必须计入。
- 持仓跨过 fundingTime 才计入资金费率。

限制：

- 必须分页下载并确认实际最早时间。
- 必须做时间戳滞后，不能把结算后才知道的数据用于结算前信号。

### 1.4 Binance 官方 REST：Open Interest Statistics

来源：

- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics

核查结果：

- 接口为 `GET /futures/data/openInterestHist`。
- 支持周期：5m / 15m / 30m / 1h / 2h / 4h / 6h / 12h / 1d。
- 官方文档写明：Only the data of the latest 1 month is available。

本研究用途：

- 只适合最近 1 个月 OI 研究或近端样本校验。
- 不足以支持多年 OI 策略穷尽搜索。

处理决定：

- 若没有第三方多年 OI，不进入多年主搜索。
- 报告中必须标记“多年 OI 不完整”。

### 1.5 Binance 官方 REST：Taker Buy/Sell Volume

来源：

- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Taker-BuySell-Volume

核查结果：

- 接口为 `GET /futures/data/takerlongshortRatio`。
- 支持周期：5m / 15m / 30m / 1h / 2h / 4h / 6h / 12h / 1d。
- 官方文档写明：Only the data of the latest 30 days is available。

本研究用途：

- 不适合多年全量策略搜索。
- 多年 K 线级 taker buy/sell 可从 futures klines 字段构造，但那是 K 线近似，不是逐笔订单流。

### 1.6 第三方 BTC 历史微观数据

可选来源：

- Tardis.dev
- Amberdata
- Kaiko 等商业数据源

核查结论：

- 这类来源可能覆盖 trades、order book、open interest、liquidations、funding 等更完整历史。
- 多数为付费，不应默认当作已获取。
- 若用户愿意使用付费源，可以扩展清算、盘口、真实订单流、OI 多年历史。

处理决定：

- 当前免费公开流程：不把 liquidation/depth 作为已完成搜索数据。
- 付费数据接入前，G/H 策略族只能部分完成。

---

## 2. XAUUSD 黄金 CFD

### 2.1 Dukascopy Historical Data Export / JForex

来源：

- https://www.dukascopy.com/swiss/english/marketwatch/historical/
- https://www.dukascopy.com/swiss/english/fx-market-tools/historical-data/

核查结果：

- Dukascopy 提供 Historical Data Export，并可通过 JForex Historical Data Manager 下载。
- 公开页面说明可获得从 tick-by-tick 到 monthly 的不同时间框架。
- 页面列出 XAU/USD live chart，并提供 Historical Data Export 工具入口。

本研究用途：

- 黄金 tick / M1 首选候选源。
- 若能取得 bid/ask tick，可用于剥头皮相对高置信度回测。

限制：

- 需要实际下载确认 XAU/USD 起止时间、字段、时区、bid/ask 口径。
- Dukascopy 报价仍是经纪商/流动性报价，不等同所有 CFD 经纪商。

### 2.2 HistData.com

来源：

- https://www.histdata.com/
- https://www.histdata.com/download-free-forex-data/

核查结果：

- HistData 明确列出 XAU/USD。
- HistData 说明数据只提供 time ordered Tick 和 M1，按 forex-pair/year/month 组织。
- Tick 数据为 1 秒报价，不等同真实逐笔成交。

本研究用途：

- 可作为免费 M1 主数据候选。
- 可作为黄金日内/波段研究基础。

限制：

- 必须确认时区、报价口径和更新时间。
- 剥头皮若用 HistData 1 秒 tick，只能视作报价近似，不是交易所逐笔成交。

### 2.3 Dukascopy 交易时段、swap、点差工具

来源：

- Forex Market Hours: https://www.dukascopy.com/swiss/english/fx-market-tools/forex-market-hours/
- Overnight Swaps: https://www.dukascopy.com/swiss/english/fx-market-tools/overnight-policy/
- Average Spreads: https://www.dukascopy.com/swiss/english/fx-market-tools/average-spreads/

核查结果：

- Dukascopy 页面说明 Forex 周一至周五 24 小时交易，周末休市；纽约周五 17:00 收盘，周日 17:00 重新开盘。
- 页面列出伦敦、纽约等主要交易时段和伦敦纽约重叠时段。
- Dukascopy 有 Overnight Swaps 和 Average Spreads 工具入口，但动态表格需实际抓取/导出确认。

本研究用途：

- 用于黄金时段标注、休市/周末缺口、低流动时段过滤。
- swap 与平均点差可做经纪商口径参考。

限制：

- 当前阶段未拿到完整历史 swap；波段系统若无法取得历史 swap，只能用保守近似。

### 2.4 CFTC COT

来源：

- https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm

核查结果：

- CFTC 发布 COT 周报，披露 futures/options 市场中达到报告标准的持仓数据。
- 报告通常基于周二数据，周五 15:30 ET 发布。
- CFTC 提供历史报告与可下载环境。

本研究用途：

- 只能作为黄金慢因子。
- 必须按发布日期滞后，不能用周二持仓数据预测周二至周五之前行情。

限制：

- COT 是期货持仓，不是 XAUUSD CFD 微观数据。
- 不适合日内/剥头皮订单流。

### 2.5 CME / COMEX Gold Futures volume & OI

来源：

- https://www.cmegroup.com/markets/metals/precious/gold.volume.html

核查结果：

- CME 提供 Gold Futures 相关 volume / open interest 工具和资料。
- COMEX 黄金期货可作为黄金市场慢因子参考。

本研究用途：

- 可做日/周级宏观或衍生品慢因子。

限制：

- 不能冒充 XAUUSD CFD 的成交量、盘口、清算或订单流。
- 期货合约涉及换月和基差处理。

---

# 明确不可用或不能冒充的数据

## BTC

1. 不能用 spot BTCUSDT 代替 USDT-M 永续 BTCUSDT。
2. 不能用普通 K 线 volume 冒充订单流。
3. 不能用 K 线 taker buy/sell 冒充逐笔 CVD，只能写“近似 CVD”。
4. 没有多年 OI 数据时，不能声称完成 OI 策略搜索。
5. 没有历史 depth/order book 时，不能声称完成盘口策略搜索。
6. 没有可靠历史 liquidation 时，不能声称完成清算策略搜索。

## 黄金

1. XAUUSD CFD 没有 Binance 式 funding rate。
2. XAUUSD CFD 没有统一公开 OI、清算、盘口、逐笔成交簿。
3. COMEX 期货数据不能冒充 CFD 微观数据。
4. tick volume 不能写成真实成交量。
5. 只用 M1 时，黄金剥头皮只能低置信度近似。

---

# 下载优先级建议

## BTC 优先级

1. Binance Vision：BTCUSDT USDT-M monthly 1m klines。
2. Binance REST：funding rate 全量分页。
3. Binance Vision：BTCUSDT aggTrades，先下载最近 3-6 个月样本评估数据量和速度，再决定是否多年全量。
4. 第三方/付费：OI、liquidation、depth，如用户确认使用。

## 黄金优先级

1. Dukascopy XAU/USD tick 或 M1，先下载 1 个月样本确认字段与时区。
2. HistData XAU/USD M1，下载若干年份样本核验连续性。
3. 经纪商 MT5 历史：如果用户有实盘经纪商，应优先使用该经纪商数据和 swap/点差。
4. CFTC COT / COMEX OI：仅作为慢因子扩展。

---

# 第一阶段最终判定

BTC 永续线：可进入后续数据下载与质量扫描，但 G/H 中的 OI、清算、盘口策略只能在实际取得数据后纳入。

黄金 CFD 线：可进入 M1/tick 报价数据下载与质量扫描；不支持完整订单流穷尽搜索；swap 若没有历史精确值，只能保守近似。

本阶段已按要求停止，不进入全量回测。
