# missing_data_request.md

生成时间：2026-06-21 UTC  
状态：本地仓库未发现可用于 BTC 合约回测的原始行情/衍生品数据；当前环境未发现交易所或商业数据 API key。因此本轮只能完成研究框架、数据审计与缺失数据清单，不能伪造回测结果。

## 本地与 API 检查结论

- 本地文件：仅发现既有 `data_sources_report.md` 与 `data_quality_report.md`，未发现 `data/`、`raw/`、`parquet/`、`csv` 行情数据目录或可回测数据库。
- 环境变量：未发现 Binance / OKX / Bybit / Tardis / Amberdata / Kaiko / Coinglass API key。
- 可公开下载：Binance Vision 的 K 线、aggTrades、trades 可作为免费主数据；Binance REST 可补近端与 funding。
- 不可用于历史回测：没有 point-in-time 历史快照的 liquidation heatmap / liquidation levels 只能用于 forward test 或实盘观察，不能用于历史信号。

## 数据优先级总览

| 优先级 | 数据 | 是否必需 | 没有时是否可跳过 | 主要用途 | 推荐来源 |
|---:|---|---|---|---|---|
| P0 | BTCUSDT USDT-M 永续 1m K 线 | 必需 | 不可跳过 | 所有周期主回测、基准、成交量与近似 CVD | Binance Vision |
| P0 | BTCUSDT funding rate 历史 | 必需 | 不可跳过永续净值评估 | 真实资金费成本、funding 单因子基准 | Binance REST `/fapi/v1/fundingRate` |
| P0 | BTCUSDT mark price / premium index K 线 | 强烈建议 | 可临时跳过但 basis/premium 模块失效 | 标记价格、基差/溢价、止损更稳健 | Binance REST / Vision 如可得 |
| P1 | BTCUSDT aggTrades 最近 12-24 个月 | 强烈建议 | 可跳过超短线订单流研究 | 真实 CVD、delta、taker imbalance、短周期冲击 | Binance Vision |
| P1 | BTCUSDT spot 1m K 线 | 强烈建议 | 可跳过 spot-perp 模块 | spot-perp divergence、basis proxy | Binance Vision Spot |
| P1 | BTCUSDT / BTCUSD COIN-M futures 1m K 线 | 建议 | 可跳过交割合约对比 | USDT-M vs COIN-M/交割合约对比 | Binance Vision COIN-M |
| P2 | 多年 open interest | 重要但非免费必需 | 可跳过 OI 策略 | 杠杆拥挤度、OI 变化、挤仓风险 | Tardis / Amberdata / Kaiko / Coinglass |
| P2 | 多年 global long/short ratio | 可选 | 可跳过 | 散户拥挤度、反向情绪 | Binance 仅近端；Coinglass 等 |
| P2 | 多年 top trader long/short ratio | 可选 | 可跳过 | 头部账户仓位情绪 | Binance 近端；Coinglass 等 |
| P2 | 多年 taker buy/sell volume 统计 | 可选 | 可用 K 线 taker 字段替代 | 主动买卖强度确认 | Binance K 线字段 / 第三方 |
| P3 | liquidation history 事件级 | 可选但有价值 | 可跳过清算模块 | 清算后反转/延续、瀑布风险 | Tardis / Amberdata / Kaiko / Coinglass |
| P3 | historical order book depth L2/L3 | 高成本可选 | 可跳过盘口模块 | 流动性、冲击成本、订单簿不平衡 | Tardis / Kaiko / Amberdata |
| P3 | liquidation heatmap 历史 point-in-time 快照 | 仅有真实快照时可用 | 无快照必须跳过历史回测 | 流动性池/猎杀观察 | Coinglass/Hyblock 等如提供历史快照 |

## 具体缺失数据清单

### 1. Binance BTCUSDT USDT-M 永续 1m K 线

- 缺什么：BTCUSDT 永续合约 1m OHLCV，至少覆盖 2019-09 至今；UTC 时间。
- 为什么需要：所有 1m/3m/5m/15m/30m/1H/4H/8H/D 策略的基础数据；可从 1m 因果聚合高周期。
- 是否必需：必需。
- 获取方式：Binance Vision `data/futures/um/monthly/klines/BTCUSDT/1m/` 与必要 daily 增量；下载 `.zip` 与 `.CHECKSUM`。
- 需要字段：open_time, open, high, low, close, volume, close_time, quote_asset_volume, number_of_trades, taker_buy_base_volume, taker_buy_quote_volume, ignore。
- 价格/难度：免费；下载和校验中等难度；多年 1m 体积可接受。
- `.env` 变量：公开数据无需 key；如用 REST 补缺可配置 `BINANCE_API_KEY`、`BINANCE_API_SECRET`，但公共行情通常无需。
- 没有时是否可以跳过：不可跳过。

### 2. Binance BTCUSDT funding rate 历史

- 缺什么：BTCUSDT 永续 fundingRate 历史，覆盖 K 线同区间。
- 为什么需要：持仓跨 fundingTime 时必须计入资金费率；也是 funding 单因子基准。
- 是否必需：永续合约净值评估必需。
- 获取方式：Binance USD-M Futures REST `GET /fapi/v1/fundingRate` 分页。
- 需要字段：symbol, fundingTime, fundingRate, markPrice。
- 价格/难度：免费；分页简单。
- `.env` 变量：通常无需；若配置则 `BINANCE_API_KEY`、`BINANCE_API_SECRET`。
- 没有时是否可以跳过：不能用于最终永续结果；只能输出 gross-only 预检且标记无效。

### 3. Binance BTCUSDT mark price / premium index

- 缺什么：mark price K 线、index price K 线、premium index 或 basis proxy。
- 为什么需要：更真实地模拟永续标记价格、资金费附近风险、spot-perp divergence。
- 是否必需：强烈建议；basis/premium 模块必需。
- 获取方式：Binance USD-M REST market data 或 Binance Vision 如有对应文件。
- 需要字段：open_time, mark/index/premium OHLC, close_time。
- 价格/难度：免费到中等；需确认历史深度。
- `.env` 变量：`BINANCE_API_KEY`、`BINANCE_API_SECRET` 可选。
- 没有时是否可以跳过：可以，但不能评估 premium/basis 策略族。

### 4. BTCUSDT aggTrades / trades

- 缺什么：BTCUSDT USDT-M 永续 aggTrades，优先最近 12 个月，理想覆盖 24-36 个月；trades 作为高成本扩展。
- 为什么需要：重建真实 CVD、delta、taker imbalance、冲击后均值回归/延续；1m K 线 taker 字段只是低频近似。
- 是否必需：超短线订单流研究必需；日内/波段非必需。
- 获取方式：Binance Vision `futures/um/monthly/aggTrades/BTCUSDT/` 或 daily 文件。
- 需要字段：agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker。
- 价格/难度：免费但数据量大；下载、压缩存储、聚合成本中高。
- `.env` 变量：公开文件无需 key。
- 没有时是否可以跳过：可以，但超短线结论只能低置信度，不能声称订单流策略完成。

### 5. Spot BTCUSDT 1m K 线

- 缺什么：Binance spot BTCUSDT 1m OHLCV，与永续同区间。
- 为什么需要：spot-perp divergence、溢价、现货确认趋势。
- 是否必需：建议。
- 获取方式：Binance Vision Spot monthly/daily klines。
- 需要字段：标准 spot K 线字段。
- 价格/难度：免费；低到中等。
- `.env` 变量：无需。
- 没有时是否可以跳过：可以，spot-perp 模块跳过。

### 6. 多年 OI / 多空比 / top trader ratio / taker stats

- 缺什么：BTCUSDT 多年 open interest、global long/short account ratio、top trader account/position ratio、taker buy/sell volume 统计。
- 为什么需要：衍生品拥挤度、趋势确认、反向情绪与挤仓风险。
- 是否必需：非必需但对衍生品策略很有价值。
- 获取方式：Binance 官方统计接口通常只保留近 30 天或 1 个月，不足以多年回测；建议 Tardis、Amberdata、Kaiko、Coinglass、CryptoQuant、Glassnode 等商业源。
- 需要字段：timestamp UTC, symbol, exchange, open_interest, open_interest_value, long_short_ratio, long_account, short_account, top_trader_long_short_ratio, taker_buy_volume, taker_sell_volume。
- 价格/难度：中高到高；不同供应商价格差异大，通常需要付费订阅。
- `.env` 变量：`TARDIS_API_KEY`、`AMBERDATA_API_KEY`、`KAIKO_API_KEY`、`COINGLASS_API_KEY`、`CRYPTOQUANT_API_KEY`、`GLASSNODE_API_KEY`。
- 没有时是否可以跳过：可以；必须在结果中标记 OI/多空比模块未完成或仅 forward。

### 7. liquidation history

- 缺什么：历史强平事件，至少 timestamp UTC、side、price、quantity、notional。
- 为什么需要：清算瀑布后的延续/反转、流动性扫荡后入场过滤。
- 是否必需：可选。
- 获取方式：Tardis、Amberdata、Kaiko、Coinglass 等；Binance 实时流只能从开始采集之后用于 forward。
- 需要字段：timestamp, exchange, symbol, side, price, quantity, notional, raw_event_id。
- 价格/难度：中高；历史数据通常付费。
- `.env` 变量：同商业源变量；若自采集实时流可用 `BINANCE_WS_CAPTURE_DIR` 指定落盘目录。
- 没有时是否可以跳过：可以；不能做历史清算策略。

### 8. historical order book / depth

- 缺什么：L2 order book snapshots 或 incremental depth updates，最好含 top 20/100/1000 档。
- 为什么需要：盘口不平衡、真实冲击成本、挂单墙、短线流动性。
- 是否必需：超短线高级研究可选；非必需。
- 获取方式：Tardis、Kaiko、Amberdata；自采集只能 forward。
- 需要字段：timestamp, bids(price,size), asks(price,size), update_id/sequence, snapshot/update 标识。
- 价格/难度：高；存储与处理成本高。
- `.env` 变量：`TARDIS_API_KEY`、`KAIKO_API_KEY`、`AMBERDATA_API_KEY`。
- 没有时是否可以跳过：可以；不能评估盘口策略。

### 9. liquidation heatmap / liquidation levels 历史 point-in-time 快照

- 缺什么：历史每个时点当时可见的 liquidation heatmap / estimated liquidation levels 快照。
- 为什么需要：只在有 point-in-time 快照时，才能验证流动性池/猎杀逻辑是否真实有效。
- 是否必需：非必需。
- 获取方式：Coinglass、Hyblock、Coinank 等如提供历史快照导出/API；必须确认是历史快照，不是当前模型回填。
- 需要字段：snapshot_time UTC, symbol, exchange_scope, price_level, estimated_liquidation_notional, leverage_bucket, methodology_version。
- 价格/难度：高；可得性不确定。
- `.env` 变量：`COINGLASS_API_KEY`、`HYBLOCK_API_KEY`、`COINANK_API_KEY`。
- 没有时是否可以跳过：必须跳过历史回测；可保留 forward test 观察接口。

## 数据到位后的自动研究流程

1. 下载并校验 P0 数据。
2. 输出 `data_coverage_report.csv`，列出每个数据集的起止时间、缺口、重复、异常。
3. 建立统一 UTC、因果 rolling、无未来函数的数据层。
4. 先跑不可调或少参数基准：buy and hold、simple momentum、simple mean reversion、funding 反向、OI 单因子、普通突破、普通 2B/sweep。
5. 再按超短线、日内、短波段分别测试候选策略族。
6. 所有交易统一计入 fee、slippage、funding；输出 `trades.csv`。
7. 严格切分 IS/OOS 与 walk-forward；OOS 不反复调参。
8. 输出失败版本、无效模块、消融、参数稳定性、bootstrap、Deflated Sharpe、PBO。
