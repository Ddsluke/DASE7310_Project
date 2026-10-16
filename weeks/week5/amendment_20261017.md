# Week 5 提交修订记录（事前修订）

- 修订时间：2026-10-17（周六），目标周 2026-10-19 ~ 10-23 **尚未开始**
- 修订性质：**事前修订（pre-outcome amendment）**，不是事后追改；所有既有文件未做任何修改

## 修订内容

1. 候选集在原有 `mean20, median20, ewma85, naive, ridge, ridge100, combo50, ridge_mkt` 基础上
   **增加 `qreg50`**（中位数回归 / 分位数回归 q=0.5，与 ridge 同特征、同协议，仅损失函数改为绝对值+L1）。
2. 依据（全部只用到 2026-10-16 及以前的数据）：
   - 课程评分 = 十只股票**绝对误差之和**；`qreg50` 的 L1 目标与评分口径一致，而 Ridge 的平方损失对应条件均值，存在目标错配；
   - 同口径实验（`research/`）：20 周冻结窗口中 qreg50 总误差 5.7467 < ridge 5.8029；
     52 周窗口中 qreg50 13.5312 < ridge 13.8830，且按周 block bootstrap 配对检验显著（p≈0.015）；
   - 近 10 周累计：qreg50 2.3273 < zero 2.3294 < ridge 2.3754。
3. 按修订后的规则重新推演 Week 5：规则自动选中 `qreg50`（α 调参结果 0.001）。

## 产物（新增文件，不动旧文件）

| 文件 | 说明 |
|---|---|
| `predictions_qreg50.csv` | **Week 5 最终提交值（4 位小数）** |
| `submission_qreg50.xlsx` | 同内容的 Excel（Moodle 用） |
| `backtest_qreg50.csv` / `backtest_detail_qreg50.csv` | 修订后候选集的 20 周冻结窗口回测 |
| `params_qreg50.json` | 本快照的截点/候选/规则/被选模型参数 |
| `report_qreg50.md` | 自动生成的快照说明 |
| `qreg50_weekly_report.md` | 本周完整报告（为什么改、为什么优于 zero/ridge） |

## 保留说明

- v1 快照（`predictions.csv` 等）保持原样，仅作历史记录；最终提交以 `predictions_qreg50.csv` 为准。
- 若目标周结束后回看：实际值记录将写为 `realized_qreg50.csv`（evaluate 命令，见 README）。
