# A股主板短线回测实验系统（gpbt）

面向“可研究”的本地回测框架：统一候选池20支，支持5分钟执行与按周统计对比；同时提供“纯日线”基线策略确保链路稳定可复现。

- 数据源：akshare（交易日历/日线）、eastmoney_curl（东财 push2his 的日线/5min）、local_files（离线导入）。可选 tushare。
- 硬约束：主板、T+1、100股取整、一字板不可成交保守处理、周五强平、无未来函数（信号在bar收盘确认、下bar开盘成交）。
- 结果：单策略明细 + 多策略汇总比较（compare_strategies.csv）。

## 安装
```bash
pip install -r requirements.txt
python gpbt.py init
```

## 一键稳定跑通（纯日线 baseline_daily）
不依赖分钟线，必出交易。示例：
```bash
python gpbt.py fetch --start 20260103 --end 20260124 --max-codes 20 --no-minutes \
  --codes 600000.SH,600028.SH,600030.SH,600036.SH,600048.SH,600104.SH,600519.SH,601166.SH,601318.SH,601398.SH,000001.SZ,000002.SZ,000333.SZ,000538.SZ,000568.SZ,000651.SZ,000725.SZ,000858.SZ,002415.SZ,002594.SZ
python gpbt.py build-candidates-range --start 20260103 --end 20260124
python gpbt.py backtest --start 20260103 --end 20260124 --strategies baseline_daily
python gpbt.py doctor --start 20260106 --end 20260106
```

## 分钟数据获取（更稳的方式：按”候选池×某天“补齐）
```bash
# 仅为某天的候选池20支抓5分钟线（eastmoney_curl），支持重试与指数退避
python gpbt.py fetch-min5-for-pool --date 20260106 --min-provider eastmoney_curl --retries 2
```
也可批量抓取：
```bash
python gpbt.py fetch --start 20260103 --end 20260110 --max-codes 30 --max-days 4 --retries 2 --min-provider eastmoney_curl
```

## 多策略对比（一次跑多策略）
策略名以逗号或多次 `--strategies` 传参：
```bash
python gpbt.py backtest --start 20260106 --end 20260106 \
  --strategies time_entry_min5,open_range_breakout,vwap_reclaim_pullback,baseline_daily

# 汇总文件：
# results/run_<run_id>/compare_strategies.csv
```
compare_strategies.csv 字段：
`strategy,n_trades,win_rate,avg_pnl,avg_win,avg_loss,payoff_ratio,total_return,max_drawdown,no_fill_buy,no_fill_sell,forced_flat_delayed,status`

Fail‑fast：若分钟线缺失超过阈值或策略无任何买入意图（NO_SIGNAL），会在汇总里标注并在控制台明确提示，避免“看似跑完但其实空结果”。

## 诊断（Doctor）
```bash
python gpbt.py doctor --start 20260103 --end 20260124
# 输出到控制台 + results/run_<run_id>/doctor_report.json：
# - 候选池文件是否存在且行数=20
# - 日线/5min 覆盖率 + 缺失清单
# - 修复命令建议（例如补抓min5）
```

## 可用策略与配置
- baseline_daily（纯日线，稳定打通）：`configs/strategies/baseline_daily.yaml`
- baseline（5min骨架）：`configs/strategies/baseline.yaml`
- time_entry_min5：`configs/strategies/time_entry_min5.yaml`
- open_range_breakout（ORB）：`configs/strategies/open_range_breakout.yaml`
- vwap_reclaim_pullback（VWAP收复）：`configs/strategies/vwap_reclaim_pullback.yaml`

共同点：
- 仅交易候选池内标的；默认 `max_positions=1` 统一可比。
- 信号在bar收盘确认，下根bar开盘成交；T+1与100股取整严格执行。
- 一字板不可成交保守处理；周五强平；资金不足跳过并记录原因。

## 目录结构
```
configs/
  config.yaml
  strategies/
    baseline.yaml
    baseline_daily.yaml
    time_entry_min5.yaml
    open_range_breakout.yaml
    vwap_reclaim_pullback.yaml
src/gpbt/
  providers/ engine/ strategy/ ...
data/
  raw/  bars/daily/  bars/min5/
universe/
  candidate_pool_YYYYMMDD.csv
results/
  run_*/
    compare_strategies.csv
    <strategy>/trades.csv | weekly_summary.csv | daily_equity.csv | metrics.json
    doctor_report.json
```

## 数据与合规
eastmoney_curl 直接调用东财 push2his 接口（研究用途），已加入重试与限速；请避免高频实时抓取。若网络不稳，建议按“候选池×某天”分段拉取，或使用 `local_files` 离线导入（将 CSV/Parquet 放到 `data/import/min5/`）。

## License
MIT, see LICENSE

## 端到端：LLM 荐股 → 回溯调参 → 盘前执行

1) 环境与密钥
- 设置 DeepSeek API Key：PowerShell `setx DEEPSEEK_API_KEY "sk-xxxx"`（或当次会话 `$env:DEEPSEEK_API_KEY="sk-xxxx"`）
- 配置：`configs/llm.yaml`（provider/base_url/model/超参）

2) 准备数据与候选池
```bash
python gpbt.py init
python gpbt.py fetch --start 20260103 --end 20260124 --max-codes 20 --no-minutes --codes 600000.SH,...
python gpbt.py build-candidates-range --start 20260103 --end 20260124
# 为分钟策略准备5min（按区间自动为每天候选池抓20只）
python gpbt.py fetch-min5-range --start 20260106 --end 20260110 --min-provider eastmoney_curl --retries 2
```

3) 盘前 LLM 荐股（缓存）
```bash
# 只对某天做rank，默认缓存：
python gpbt.py llm-rank --date 20260106 --template momentum_v1
```

4) 回溯调参并落盘 current_policy
```bash
python gpbt.py tune --end 20260110 --lookback-weeks 4 --eval-weeks 2 \
  --templates momentum_v1,pullback_v1,defensive_v1 --entries baseline --exits next_day_time_exit --topk 3
# 产物：
# data/policies/current_policy.json
# data/policies/scores.csv
```

5) 盘前执行（读取 current_policy、调用 LLM、按策略执行）
```bash
python gpbt.py llm-run --start 20260106 --end 20260110 --run-id llm_live_20260110
# 产物：results/run_llm_live_20260110/
#  - trades.csv / weekly_summary.csv / metrics.json
#  - policy_used.json（本次使用的策略）
#  - llm_used/（调用的输出索引）
```

Fail-fast 原则（无兜底）：
- LLM 缺失/失败、JSON 不合法、越界/不足 TopK → 命令立即失败（非0退出）
- 分钟线缺失超过阈值 → 直接失败，列出“缺失日期+代码”
- T+1 严格：不允许同日买卖同一标的
