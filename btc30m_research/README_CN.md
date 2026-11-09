任务受阻，没能完成（流程测试草稿：只含基线 B0，搜索尚未开始；最终报告会整体替换本文件）

# 流程测试草稿

- 数据：data.binance.vision，BTCUSDT 指数价 1m K 线 2020-01-01 → 2025-12-31（研究数据最大时间戳 2025-12-31T23:59:00Z）。
- 基线 B0（试验 1）：方向 = sign(P(T−1) − P(T−31))，每分钟出信号。
- 流程：下载 → 回测 → frozen/ → signals_dev.csv、signals_val.csv → results.json，全部跑通；frozen 输出与研究代码逐行一致；24 个截断点、换起点重跑、打乱对照均已跑通。
- 详细数字见 results.json（只用于验证流程，不是结论）。
