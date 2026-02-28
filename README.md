## A股主板短线回测实验系统（候选池20 + 5min执行 + 周度对比）

本项目按《项目计划.txt》进行方向纠偏式重构，将原有 gp_assistant 主文档改为以回测实验系统为主。旧助手说明见 `docs/assistant.md`（docker-compose 仍可运行）。

核心约束（默认）
- 仅沪深主板；默认剔除 ST/*ST；默认剔除上市不足 `min_list_days` 的新股；
- 每天盘前生成候选池 Top20；盘中以 5 分钟K 执行；统一成交口径：信号在某根 5min bar 收盘确认后，下一根 bar 开盘成交（+滑点）；
- 严格 T+1；周一开始，周五收盘强制清仓；
- 输出每策略：胜率/单笔期望/盈亏比/最大回撤/交易次数/不可成交次数（涨停买不到/跌停卖不出）。

从 0 到跑通（命令）
- `python -m scripts.fetch_basics --provider tushare --start 20180101 --end 20251231`
- `python -m scripts.fetch_daily --provider tushare --start 20180101 --end 20251231`
- `python -m scripts.build_candidate_pool --date 20250106 --pool_size 20`
- `python -m scripts.fetch_min5_for_pool --date 20250106`
- `python -m backtest.runner_weekly --config configs/config.yaml --strategies configs/strategies/*.yaml --start 20200101 --end 20251231 --run_id demo_001`
- `python gpbt.py doctor --date 20250106`

无法使用 Tushare 分钟权限时如何切换：
- 改用 `--provider akshare`。分钟接口使用 `stock_zh_a_hist_min_em`，可能仅能获取近期数据且存在频控限制；本项目脚本接口与 Tushare 对齐，可无缝切换。

项目结构（关键新增）
- `src/providers/`: 数据提供接口（Tushare/AkShare）与本地 Parquet 存储
- `src/scripts/`: 数据抓取与候选池脚本（支持 `python -m scripts.xxx`）
- `src/selector/selector_v1.py`: 可解释 V1 打分（趋势/动量/流动性/波动惩罚/公告关键词）
- `src/strategies/`: 策略插件体系（baseline/breakout/pullback/openrange）
- `src/backtest/`: 回测引擎、周度运行器、指标汇总
- `results/run_{run_id}/`: `trades.csv`, `daily_equity.csv`, `weekly_summary.csv`, `metrics.json`

配置（见 `configs/config.yaml`）
- `market=mainboard`、`pool_size=20`、`min_list_days=60`、`exclude_st=true`
- `initial_cash=1_000_000`、`max_positions`、费用参数、`force_flat_on_friday_close=true`

可选 CLI（便捷封装）
- 初始化: `python gpbt.py init`
- 一次性抓取: `python gpbt.py fetch --provider tushare --start 20180101 --end 20251231`
- 生成候选池: `python gpbt.py build-candidates --date 20250106`
- 拉分钟数据: `python gpbt.py fetch-min5-for-pool --provider tushare --date 20250106`
- 回测: `python gpbt.py backtest --config configs/config.yaml --strategies configs/strategies/*.yaml --start 20200101 --end 20251231 --run_id demo_001`

测试与断言（离线 fixtures）
- 新增单元测试（见 `tests/`）：
  1) 无未来函数：候选池生成只用 ≤ 前一交易日数据；策略只能访问当前 bar 及以前
  2) T+1 强制：买入当日出现卖出 intent 不得成交
  3) 一字板不可成交挂起：构造涨停/跌停 bar 序列验证挂起逻辑与计数
  4) 费用一致性：对一笔已知交易手算费用与程序一致

提示
- 仓库根目录已包含 `sitecustomize.py`，可确保 `src/` 布局下使用 `python -m scripts.xxx` 直接运行。
- 若需安装包方式使用，也可 `pip install -e .`。
