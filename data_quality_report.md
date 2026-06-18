# data_quality_report.md

生成时间：2026-06-19
阶段：第一阶段——数据质量检查与数据补充可行性检查
状态：已完成公开来源核查；未开始全量回测。

## 执行边界

本阶段只做数据可得性、口径、适配性与风险检查，不做策略搜索，不做 A+ 复现，不输出排行榜。

当前连接到的 GitHub 仓库 `xuanjiantao742-crypto/Xuan` 显示仓库体积为 0，未发现可归档的旧 `checkpoint / logs / results` 文件。因此本阶段未移动旧结果，也未删除任何旧结果。

当前会话无法直接在用户本地工作区执行 shell/git 命令；本报告基于公开来源核查生成。后续真正下载全量数据时，必须在本地 agent 或云端 runner 中执行目录枚举、文件下载、checksum 校验、缺失 K 线扫描和异常价格扫描。

---

# 线 A：BTCUSDT USDT-M 永续

## A1. 数据主结论

BTC 永续线可以支持：

- 日内策略：可以支持，主数据为 USDT-M 永续 1m K 线。
- 波段策略：可以支持，1m 聚合为 1h / 2h / 4h / 1d。
- BTC 剥头皮：只有拿到 Binance Vision 的 `aggTrades` / `trades` 后才可高置信度支持；若只有 1m K 线，只能低置信度近似。
- funding 策略：可支持，但必须实际分页下载 funding rate，并按 fundingTime 对齐。
- OI 策略：官方 REST 历史统计接口只给最近 1 个月，不能直接覆盖全量历史；若需要多年 OI，需另找付费/第三方历史数据或自行采集。
- taker buy/sell volume：K 线本身含 taker buy base/quote volume，可构造 K 线级近似 CVD；但 Binance futures/data 的 taker buy/sell 统计接口只给最近 30 天，不能覆盖全量历史。
- liquidation / depth：免费全量历史不可稳定取得，不应声称完成清算/盘口穷尽搜索。

## A2. 数据集检查表

| 数据 | 类型口径 | 能否获取 | 预期时间范围 | 周期/粒度 | 质量风险 | 是否适合本次回测 | 处理决定 |
|---|---|---:|---|---|---|---|---|
| BTCUSDT USDT-M 永续 1m K 线 | 永续，不是现货 | 可以 | 需目录枚举确认；预期从合约上线后开始，约 2019-09 附近 | 1m，可聚合 5m/15m/30m/1h/2h/4h/1d | 月包/daily 包缺口、交易所补档、时间戳一致性 | 适合日内/波段主回测 | 必须下载并 checksum 校验 |
| BTCUSDT funding rate | 永续资金费率 | 可以通过官方 REST 分页 | 需实际 API 分页确认；样例包含 2019-10 附近时间戳 | 资金费结算点 | 必须按真实可得时刻对齐，不得提前使用 | 适合 BTC 永续真实 PnL | 必须纳入 BTC 过 fundingTime 持仓 |
| BTCUSDT OI / open interest | 衍生品持仓量 | 官方 REST 仅最近 1 个月；多年历史需第三方或自行采集 | 官方 REST 不足以覆盖多年 | 5m 到 1d | 历史不足；不能拿最近 1 月冒充全样本 | 只适合最近 1 月 OI 策略，或作为付费数据扩展 | 第一阶段标记“部分可得/全量不可得” |
| BTCUSDT K 线 taker buy/sell volume | K 线内主动买量字段 | 可以随 K 线获得 | 跟随 K 线 | 1m 起 | 只能算近似 CVD，不是逐笔订单流 | 适合低频/中频成交量因子 | 标记“近似 CVD” |
| BTCUSDT futures/data taker buy/sell volume | Binance 衍生品统计接口 | 官方 REST 只给最近 30 天 | 最近 30 天 | 5m 到 1d | 历史太短 | 不适合多年全量搜索 | 不作为主数据 |
| BTCUSDT aggTrades | 聚合逐笔成交 | Binance Vision 可尝试；REST 只适合近端/短窗口 | 需目录枚举确认 | 逐笔聚合 | 文件量大；下载/存储成本高 | BTC 剥头皮首选数据 | 可做 5s/15s/30s 聚合，但需先下载样本 |
| BTCUSDT trades | 原始成交 | Binance Vision 可尝试；REST 历史受限 | 需目录枚举确认 | 逐笔 | 文件量极大 | 可用于订单流/剥头皮，但成本很高 | 优先 aggTrades，trades 作为扩展 |
| BTCUSDT liquidation | 强平/清算 | 免费全量历史大概率不可得；实时流可采集 | 无可靠免费全量历史 | 事件级 | 历史回填难；第三方可能付费 | 不适合当前免费全量搜索 | 标记不可得，除非接入付费源 |
| BTCUSDT depth / order book | 盘口 | 历史免费数据基本不可得；实时可采集 | 无可靠免费全量历史 | L2/L3 | 无历史快照无法回测挂单墙/队列 | 不适合当前免费全量搜索 | 标记不可得，除非付费源 |

## A3. BTC 支持的策略族

| 策略族 | 支持状态 | 说明 |
|---|---|---|
| A 趋势类 | 支持 | 由永续 K 线计算 |
| B 动量类 | 支持 | 由永续 K 线计算 |
| C 波动类 | 支持 | ATR / HV / 布林等均可 |
| D 成交量类 | 支持但需标注 | K 线 volume 与 taker buy/sell volume；CVD 只能分为 K 线近似和 aggTrades 真实聚合两类 |
| E 价格行为类 | 支持 | 由 OHLC 计算 |
| F 时间类 | 支持 | UTC 小时/星期、资金费结算点、周末等 |
| G 衍生品类 | 部分支持 | funding 可支持；OI 官方历史不足；清算/基差/多空比需看额外数据源 |
| H 订单流类 | 条件支持 | aggTrades 可支持逐笔/聚合 CVD；depth/liquidation 免费历史不足 |

## A4. BTC 数据质量落地检查清单

真正下载后必须执行：

1. 枚举 Binance Vision 目录，确认首月与末月，不准假设起止。
2. 下载 monthly 1m klines，并用 `.CHECKSUM` 校验。
3. 检查 open time 是否严格 60 秒递增。
4. 检查缺失 K 线、重复 K 线、乱序 K 线。
5. 检查 OHLC 逻辑：`low <= open/close <= high`。
6. 检查异常价格跳变：例如单根收益绝对值超过合理阈值，需要人工确认是否交易所真实波动。
7. 检查成交量、quote volume、number of trades 是否为非负。
8. 检查 taker buy volume 是否不超过 total volume。
9. 统一 UTC，不做本地时区偏移。
10. funding 按 `fundingTime` 对齐，只对跨过结算时刻的持仓计入。

---

# 线 B：XAUUSD 黄金 CFD

## B1. 数据主结论

黄金 CFD 线可以支持：

- 日内策略：可以支持，主数据为 XAUUSD M1 OHLCV 或 bid/ask tick 聚合数据。
- 波段策略：可以支持，但必须建模 swap，并明确周末跳空风险。
- 黄金剥头皮：只有拿到 tick 或干净 M1 + bid/ask/点差数据后才有较高可信度。若只有 M1 mid/bid 数据，剥头皮只能低置信度近似。
- 订单流穷尽搜索：不支持。黄金 CFD 是 OTC/分散报价，没有 Binance 式集中交易所的公开逐笔成交、公开清算、统一盘口、公开 funding/OI。
- 衍生品慢因子：可选 COMEX 黄金期货 volume/OI 或 CFTC COT，但只能标注为“COMEX 期货近似，非 CFD 微观数据”。

## B2. 数据集检查表

| 数据 | 类型口径 | 能否获取 | 预期时间范围 | 周期/粒度 | 质量风险 | 是否适合本次回测 | 处理决定 |
|---|---|---:|---|---|---|---|---|
| XAUUSD M1 OHLCV - HistData | Forex/CFD 报价数据，不是 COMEX 期货 | 可以尝试 | 需下载页确认；来源声明按年月组织 | M1 / tick 1 秒报价 | 数据更新时间、时区、bid/ask/mid 口径需核验；volume 多为 tick volume | 适合日内/波段主回测 | 可作为免费主数据候选 |
| XAUUSD tick/M1 - Dukascopy | Dukascopy 报价数据 | 可以尝试 | 需 Historical Data Export/JForex 实测 | tick 到 monthly | 下载流程较重；需确认 XAU/USD 可用区间、bid/ask 与点差 | 更适合黄金剥头皮与点差敏感性 | 优先用于剥头皮样本 |
| Stooq / 免费日线或较低频 | 现货/报价数据 | 可尝试 | 依源而定 | 通常非 M1 | 频率可能不足 | 可做辅助检查，不作为 M1 主源 | 低优先级 |
| Twelve Data / Alpha Vantage | API 数据 | 可尝试 | 免费额度有限 | 取决于套餐 | 免费额度/历史深度不足 | 不适合全量穷尽搜索 | 仅做补充或抽样校验 |
| MT5 经纪商导出 | 经纪商 CFD 真实口径 | 可以，如果有账户/终端 | 依经纪商 | M1/tick 视经纪商 | 不同经纪商点差、swap、时区不同 | 很适合实盘口径，但可复现性弱 | 若用户有指定经纪商，优先使用 |
| swap / overnight fee | 经纪商库存费 | 可从经纪商/平台取当前值，历史通常难 | 历史精确值难 | 每日/方向 | 多空不同，周三三倍，随利率变化 | 波段必需；日内可忽略 | 拿不到历史则用保守常数并标注近似 |
| COMEX Gold futures volume/OI | 期货慢因子 | 可尝试 | 依 CME 数据权限 | 日级/合约级 | 与 CFD 有基差、时段和换月差异 | 只能做慢因子，不是 CFD 微观数据 | 标注“COMEX 近似” |
| CFTC COT | 期货持仓周报 | 可以获取 | 历史较长 | 周频 | 发布滞后：周二数据，周五发布 | 只能做慢因子，不能做日内订单流 | 可选扩展 |
| CFD 订单流 / 盘口 / 清算 | CFD 微观数据 | 不支持公开全量 | 无 | 无 | OTC 分散市场，无统一公开成交簿 | 不适合 | 明确跳过，不假装搜索 |

## B3. 黄金支持的策略族

| 策略族 | 支持状态 | 说明 |
|---|---|---|
| A 趋势类 | 支持 | M1 聚合或高周期 OHLC 计算 |
| B 动量类 | 支持 | RSI / Stoch / CCI / ROC 等 |
| C 波动类 | 支持 | ATR / HV / BB Width 等 |
| D 成交量类 | 弱支持 | 多数为 tick volume，不是真实成交量，必须标注 |
| E 价格行为类 | 支持 | 突破/假突破/K 线结构可做 |
| F 时间类 | 支持 | 亚洲/伦敦/纽约/重叠时段、休市前后、周一开盘 |
| G 衍生品类 | 只支持慢因子近似 | COMEX OI/COT，不是 CFD 级衍生品 |
| H 订单流类 | 不支持完整穷尽搜索 | 无公开统一逐笔成交/盘口/清算 |

## B4. 黄金数据质量落地检查清单

真正下载后必须执行：

1. 确认原始时区，统一转 UTC。
2. 确认价格口径：bid / ask / mid / last，不能混用。
3. 确认是否有历史点差；没有则必须用保守固定点差和滑点敏感性。
4. 检查 M1 连续性，标记每日休市、周末休市、周一首根。
5. 检查异常价格、缺口、负价/零价。
6. 检查 OHLC 逻辑：`low <= open/close <= high`。
7. 检查 tick volume 是否为非负；不得把 tick volume 写成真实成交量。
8. 日内策略必须在休市前强平。
9. 波段策略必须计入 swap；若无历史精确 swap，使用保守近似，并单独输出敏感性。
10. 剥头皮必须使用 tick 或至少 bid/ask M1；若只用 M1 OHLC，结果标低置信度。

---

# 第一阶段停点结论

1. BTC 永续：价格、K 线级成交量、K 线级 taker buy/sell、funding 基本可支持；OI 多年历史、清算、历史盘口需要第三方/付费或自行采集。
2. 黄金 CFD：M1/tick 报价可尝试；swap 可近似或用经纪商当前规则；不存在 Binance 式 funding/OI/清算/订单簿公开全量数据。
3. 下一步不能直接全量回测。必须先在本地 runner 下载样本数据，完成 checksum、缺失、异常、时区、字段口径验证。
4. A+ 基准复现不能开始，除非仓库或用户提供 A+ 代码/逐笔交易；当前仓库未发现 A+ 文件。
