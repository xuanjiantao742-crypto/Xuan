# BTC 合约交易策略研究框架总结

生成时间：2026-06-21 UTC  
当前阶段：数据审计与研究框架设计完成；因本地缺少 P0 数据，未运行任何回测，未生成逐笔交易结果。

## 1. 直接判断

### 1.1 BTC 合约更适合超短线、日内还是短波段？

在没有付费 L2/逐笔历史数据之前，BTC 合约最适合优先研究 **日内 15m/30m/1H** 与 **短波段 4H/8H/D**，其次才是 1m/3m/5m 超短线。

原因：

- 超短线优势高度依赖真实订单流、盘口、延迟、撮合与手续费等级；只用 1m K 线很容易高估收益。
- 日内周期仍能使用免费 K 线、taker buy volume、funding、spot-perp proxy，且交易频率较低，成本误差相对可控。
- 短波段对数据质量要求最低，资金费率成本必须计入，但滑点/手续费对结论的破坏相对较小。

初始优先级：

1. **日内：15m/30m/1H**，主攻波动收缩后突破、趋势回调、VWAP/Session 行为、资金费附近过滤。
2. **短波段：4H/8H/D**，主攻波动调整趋势、风险状态切换、funding/basis 过滤。
3. **超短线：1m/3m/5m**，只有拿到 aggTrades 或 trades 后再做真实 CVD/order-flow；否则只做低置信度预检。

### 1.2 哪类数据最值得用？

最值得优先投入的数据：

1. **永续 1m K 线 + taker buy base/quote volume**：性价比最高，是所有基准、日内和波段研究的基础。
2. **funding rate 历史**：永续净收益不可缺少，也可作为拥挤度/反向因子。
3. **spot 1m K 线 + mark/index/premium**：用于 spot-perp divergence、basis/premium、异常溢价过滤。
4. **aggTrades 最近 1-2 年**：用于真实 CVD 与主动买卖冲击，是超短线研究的最低可信门槛。
5. **多年 OI**：若能低成本获得，非常值得；可用于杠杆拥挤、趋势确认、挤仓风险。

### 1.3 哪类策略逻辑最可能有效？

更可能有真实可交易优势的逻辑：

- **市场状态分类 + 分策略**：趋势/震荡/高波动/低波动分开处理，而不是一个规则打全市场。
- **波动收缩后的方向性突破**：使用 ATR/HV/布林带宽压缩、session high/low、VWAP 偏离作为过滤。
- **趋势回调延续**：高周期趋势确认，低周期回调到 VWAP/EMA/前结构位后入场。
- **流动性扫荡后的确认入场**：普通 2B/sweep 不能只看刺破，需要收回、成交量/delta 或波动状态确认。
- **funding/basis 作为过滤而非单独交易**：极端 funding 常代表拥挤，但单因子反向容易长期失效。
- **OI 变化 + 价格方向**：价格涨且 OI 上升、价格跌且 OI 上升、价格逆 OI 的状态含义不同；但必须有多年 OI 数据。

### 1.4 是否需要购买高端数据？

不一定。若目标是先找日内/短波段可交易优势，免费 Binance Vision + REST 足够开始。若目标是严肃研究超短线、订单流、清算与盘口，则需要购买或接入高端数据。

建议：

- 第一阶段不要先买最贵数据；先用 P0/P1 免费数据跑完稳健性流程。
- 如果日内/波段结果没有明显边际，再考虑 OI/清算/盘口是否能带来增量。
- 如果目标明确是 1m 内剥头皮，则应优先购买或下载 aggTrades，L2 深度是更高阶但成本很高。

## 2. 拟研究策略族

### 2.1 超短线 1m / 3m / 5m

候选：

- `SCALP_ORDERFLOW_CVD`：真实 aggTrades 聚合 CVD，结合价格新低/新高但 delta 不确认的背离。
- `SCALP_LIQUIDITY_SWEEP_CONFIRM`：扫前 N 根高低点后收回，必须有成交量/delta 确认；没有逐笔数据时只做低置信度版本。
- `SCALP_VWAP_REVERSION`：在低趋势、低波动状态下，远离滚动 VWAP 后均值回归。

主要失效环境：趋势单边加速、新闻冲击、手续费等级过高、滑点恶化、盘口薄。

### 2.2 日内 15m / 30m / 1H

候选：

- `INTRADAY_REGIME_BREAKOUT_PULLBACK`：低波动压缩后突破，回踩 VWAP/EMA/结构位入场，ATR 止损，session/time filter。
- `INTRADAY_SWEEP_TO_VWAP`：亚洲/伦敦/纽约 session 高低点 sweep 后回归 VWAP。
- `INTRADAY_MOMENTUM_WITH_FUNDING_FILTER`：趋势动量只在 funding 不极端拥挤时交易。

主要失效环境：低波动假突破、频繁来回扫、交易所异常波动、宏观事件前后。

### 2.3 短波段 4H / 8H / D

候选：

- `SWING_VOL_ADJUSTED_TREND`：高周期趋势 + 波动目标仓位 + funding 成本过滤。
- `SWING_BREAKOUT_WITH_BASIS_FILTER`：突破只在 premium/basis 不过度拥挤时跟随。
- `SWING_FUNDING_EXTREME_REVERSAL`：极端 funding 后只在价格结构转向时反向，不做纯 funding 反向。

主要失效环境：长期震荡、资金费持续极端但价格继续单边、重大政策/交易所风险。

## 3. 成本模型

所有最终结果必须扣除：

- 手续费：按交易所 taker/maker 档位分别建模；默认保守使用 taker fee。
- 滑点：按 bps 固定 + 波动/成交量敏感模型；超短线必须做更高滑点敏感性。
- funding：持仓跨越 fundingTime 时按实际 fundingRate 计入，多空方向相反。
- 资金利用率：仓位、杠杆、保证金占用必须一致，不用名义收益掩盖爆仓风险。

## 4. 回测与验证协议

禁止事项：

- 不允许未来函数。
- 不允许伪造缺失数据。
- 不允许只展示最好结果。
- 不允许用 OOS 反复调参。
- 不允许把未来才知道的数据提前用于历史信号。
- rolling 指标必须只使用当时及之前数据，信号生成后下一根或可成交时刻执行。

验证：

- IS/OOS 固定切分，OOS 只评估一次。
- Walk-forward：滚动训练/选择参数，下一窗口交易。
- 成本敏感性：手续费、滑点、funding 分别做压力测试。
- 因子消融：逐个移除 funding、volume、taker imbalance、vol regime、time filter 等模块。
- 参数稳定性：相邻参数网格结果必须平滑，不能单点突出。
- Bootstrap：按交易块或日期块重采样，估计收益分布。
- Deflated Sharpe：扣除多重试验后的 Sharpe 显著性。
- PBO：用 combinatorially symmetric cross-validation 评估过拟合概率。

## 5. 当前已输出文件

- `summary.md`：本研究框架、优先级、策略族、验证协议与当前结论。
- `data_coverage_report.csv`：本地数据覆盖检查；当前所有 BTC 关键数据均为 missing。
- `missing_data_request.md`：缺失数据、用途、必需性、来源、字段、难度、`.env` 变量名。
- `all_versions_ranking.csv`：版本排行榜占位；所有版本为 `not_run` 或 `blocked`，原因是缺少 P0/P1 数据。

## 6. 当前不能输出的内容

由于缺少 P0 原始数据，以下内容本轮不能真实输出：

- OOS 结果。
- Walk-forward 结果。
- 成本敏感性数值。
- 因子消融数值。
- 参数稳定性图表/表格。
- Bootstrap 检验数值。
- Deflated Sharpe。
- PBO。
- 逐笔交易 `trades.csv`。
- 最终可实盘候选系统。

这些内容不能用假数据填充；必须在数据补齐后运行。

## 7. 失败版本和无效模块

当前阶段判定为 blocked/invalid 的模块：

- `SCALP_ORDERFLOW_CVD`：缺 aggTrades/trades，不能重建真实 CVD。
- `OI_SINGLE_FACTOR`：缺多年 OI，Binance 官方统计接口历史过短。
- `LONG_SHORT_RATIO_FACTOR`：缺多年多空比与 top trader ratio。
- `LIQUIDATION_REVERSAL`：缺历史强平事件。
- `ORDER_BOOK_IMBALANCE`：缺历史 L2/L3 depth。
- `LIQUIDATION_HEATMAP_LEVELS`：缺 point-in-time 历史快照；禁止用于历史回测。

## 8. 初步答案

1. 最强策略是什么？  
   当前不能声称已有最强策略；数据缺失，未回测。最值得优先验证的是 **日内 regime breakout/pullback + funding/premium 过滤 + ATR 风控**。

2. 它为什么可能有效？  
   BTC 永续在波动收缩后常出现杠杆资金推动的方向性扩张；加入状态过滤和成本约束可减少震荡期假突破。

3. 它在哪些环境失效？  
   低波动横盘、假突破密集、新闻跳变、极端 funding 持续单边、滑点扩大时失效。

4. 扣除手续费、滑点、资金费率后是否仍然有效？  
   未知，必须等 P0 数据补齐后验证；当前不能包装成有效。

5. 是否显著优于简单基准？  
   未知，必须与 buy and hold、simple momentum、mean reversion、funding 反向、OI 单因子、普通突破、普通 2B/sweep 对比。

6. 是否存在严重过拟合？  
   当前未调参，尚无过拟合结论；后续用 Deflated Sharpe 与 PBO 检查。

7. BTC 合约更适合超短线、日内还是短波段？  
   在免费数据条件下优先日内和短波段；超短线需要 aggTrades/盘口等高质量微观数据。

8. 哪些数据真正有价值？  
   1m 永续 K 线、funding、spot/mark/premium、aggTrades、多年 OI 最有价值。

9. 哪些数据没用或性价比低？  
   无 point-in-time 的 liquidation heatmap 对历史回测无效；没有多年覆盖的 OI/多空比只能 forward，不能证明历史优势；高价 L2 深度若没有明确超短线执行能力，初期性价比低。

10. 下一步需要做什么？  
   先补齐 `missing_data_request.md` 的 P0 数据：BTCUSDT USDT-M 1m K 线与 funding rate。之后自动运行数据覆盖、基准、候选策略、OOS/walk-forward 与稳健性检验。
