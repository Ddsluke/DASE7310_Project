# DASE7310 GP1 - 周收益率预测 repo（单一脚本 + 每周快照）

本 repo 从 Week 5 起作为小组的**唯一预测流水线**：一个脚本（`forecast.py`）负责全部数据与建模；
每周生成一个不可追改的快照目录（`weeks/weekN/`）；`ledger.md` 是周度台账（提交值 + 实际值 + 误差）。

> 政策：**不允许事后追改**。快照生成与实际收益记录是两个独立步骤；已生成文件只增不改。

## 目录结构

```
forecast.py          唯一脚本（refresh-data / backtest / snapshot / evaluate）
requirements.txt     依赖清单（用 dase7310 环境）
data/                数据缓存（hfq 日/周收盘、周收益、指数、meta.json）
weeks/week1..week5/  每周快照:
    predictions.csv      提交值（4 位小数）【本快照设计提交值】
    submission.xlsx      同名 Excel（Moodle 用）
    params.json          截点/源/候选/选择规则/被选模型/参数
    backtest.csv         冻结窗口回测汇总
    backtest_detail.csv  逐周逐股误差明细（含参考基准 zero）
    report.md            自动生成的方法说明
    realized*.csv        【期末追加】实际收益与逐股误差（不得回填进 predictions）
ledger.md            周度台账（人工维护，只增不改）
CHANGELOG.md         变更记录
```

## 冻结口径（2026-10-16 起）

- 数据：AkShare；整批优先东方财富、失败则整批切新浪；**后复权 hfq** 日收盘。
- 周定义：W-FRI 当周最后一个已实现收盘价；`r[t] = P[t]/P[t-1] - 1`。
- Ridge（基线）：`lag1,lag2,lag3,mean4,std4,mean8,std8` + 股票哑变量；
  训练=最近 **156** 个已知目标周（十股合并）；`alpha ∈ {1,10,100}` 在更早 **8** 个已知目标周上按绝对误差选择。
- `ridge_mkt`：在 Ridge 基础上加 `hsi_lag1, hstech_lag1`（上一已完成周的恒指/恒生科技周收益）。
- 冻结回测窗口：截止日前最近 **20** 个已知目标周（十股同一窗口、同一口径比较）。

## 提交模型选择（预注册规则，快照生成前固定）

1. 可提交候选：`mean20, median20, ewma85, naive, ridge, ridge100, combo50, ridge_mkt`；
   `zero`（全零）只作参考展示，不作为提交候选。
2. `combo50 = 0.5*ridge + 0.5*mean20`：仅当窗口总绝对误差**同时低于两个成分**、
   且相对更优成分**至少赢在 5/10 只股票上**（避免由单股偶然造成）时，才算合格候选。
3. `ridge_mkt`：仅当窗口总绝对误差**低于 ridge** 时才算合格候选。
4. 在合格候选中取**窗口总绝对误差最小**者提交。

## 使用

```powershell
# 环境修正（该机器 MKL 与 llvm-openmp 冲突，跑 sklearn 前必须设置）
$env:MKL_THREADING_LAYER = 'SEQUENTIAL'
$py = 'C:\Users\Administrator\miniforge3\envs\dase7310\python.exe'

& $py forecast.py refresh-data                              # 拉取最新数据到 data/
& $py forecast.py backtest   --cutoff 2026-10-16            # 只跑冻结窗口回测（不动快照）
& $py forecast.py snapshot   --cutoff 2026-10-16 --week week5   # 生成周快照（提交值在 predictions.csv）
& $py forecast.py evaluate   --week week4                   # 目标周结束后记录实际收益
& $py forecast.py evaluate   --week week4 --values weeks/week4/submitted_values.csv --suffix submitted
```

## 历史记录说明

- `weeks/week1..week3`：按当时提交文件/报告忠实重建的研究快照（W1 为未复权 yahoo 口径，仅存档留证，不用 hfq 重算）。
- `weeks/week4`：双记录——`submitted_values.csv`（当时实际提交的值，与 Week 3 相同）与
  `predictions.csv`（按 week3_ridge.py 流程在 2026-10-09 截止时**正确重建**的预测值）。
- 所有更正都**以新文件形式留痕**，不覆盖旧文件。
