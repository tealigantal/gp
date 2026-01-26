# A股主板短线回测实验系统（gpbt）

一个可复现实验的回测系统：统一候选池20支、支持5分钟执行与周度比较。提供“纯日线”基线策略先打通全链路，再接入分钟策略。

- 数据源：akshare（交易日历/日线）、eastmoney_curl（push2his 日线/5min）、local_files（离线导入）。可选 tushare。
- 约束：主板、T+1、不可成交保守处理、周五强平、按周汇总。
- 输出：胜率、收益、回撤、交易次数、不可成交次数等。

## 快速开始（纯日线，稳定必出交易）

```bash
pip install -r requirements.txt
python gpbt.py init
python gpbt.py fetch --start 20260103 --end 20260124 --max-codes 20 --no-minutes \
  --codes 600000.SH,600028.SH,600030.SH,600036.SH,600048.SH,600104.SH,600519.SH,601166.SH,601318.SH,601398.SH,000001.SZ,000002.SZ,000333.SZ,000538.SZ,000568.SZ,000651.SZ,000725.SZ,000858.SZ,002415.SZ,002594.SZ
python gpbt.py build-candidates-range --start 20260103 --end 20260124
python gpbt.py backtest --start 20260103 --end 20260124 --strategies baseline_daily
python gpbt.py doctor --start 20260106 --end 20260106
```

## 5分钟数据（候选池当日补齐，更稳）

```bash
# 为某天候选池20支抓取5分钟线（eastmoney_curl 更稳），可重试
python gpbt.py fetch-min5-for-pool --date 20260106 --min-provider eastmoney_curl --retries 2

# 分钟策略回测（若当日缺失>10%会直接报错并列出缺失清单）
python gpbt.py backtest --start 20260106 --end 20260106 --strategies baseline
```

## 诊断（Doctor）

```bash
python gpbt.py doctor --start 20260103 --end 20260124
# 输出到控制台 + results/run_<run_id>/doctor_report.json
# 含：候选池(是否=20)、日线/分钟覆盖率与缺失清单、修复命令建议
```

## 主要命令
- `init`：初始化目录
- `fetch`：抓基础/日线；可用 `--min-provider eastmoney_curl` 抓分钟线，支持 `--retries --max-days --max-codes --codes`
- `build-candidates[-range]`：生成候选池Top20
- `fetch-min5-for-pool`：仅为某天候选池20支抓5分钟
- `backtest`：运行回测（`baseline_daily` 或 `baseline`）
- `doctor`：数据与配置诊断，fail-fast 避免空结果

## 策略
- `baseline_daily`（纯日线）：每日开盘买TopK、次日开盘卖、周五强平、T+1。参数见 `configs/strategies/baseline_daily.yaml`。
- `baseline`（5min骨架）：固定时刻买入，次日开始可卖；需要5分钟数据。

## 目录结构
```
configs/
  config.yaml
  strategies/
    baseline.yaml
    baseline_daily.yaml
src/gpbt/
  providers/ engine/ strategy/ ...
data/
  raw/  bars/daily/  bars/min5/
universe/
  candidate_pool_YYYYMMDD.csv
results/
  run_*/ (trades.csv, daily_equity.csv, weekly_summary.csv, metrics.json, doctor_report.json)
```

## License
MIT, see LICENSE
