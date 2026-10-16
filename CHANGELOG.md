# CHANGELOG

## 2026-10-16
- 从零创建 repo：单一脚本 `forecast.py`（refresh-data / backtest / snapshot / evaluate 四个子命令）。
- 冻结口径与预注册选择规则写入脚本头注释与 README。
- 记录 Week 1–4 历史快照：
  - week1–week3 按当时提交文件忠实重建；
  - week4 双记录（实际提交值 = Week 3 值；按 week3_ridge.py 流程在 10-09 截止的正确重建值）。
- 生成 Week 5 快照（截止 2026-10-16，目标周 2026-10-19 ~ 10-23）。
- 创建 `ledger.md` 周度台账（只增不改）。

## 2026-10-17
- 新增 `research/` 研究实验台：16 个候选（含新方案：分位数回归 qreg50、Huber、Winsorized Ridge、直方图梯度提升 gbm、
  集成与收缩变体）在 20 周与 52 周两个冻结窗口上的同口径对比；按周 block bootstrap 配对显著性检验。
- 关键发现（详见 `research/REPORT_NOTES.md`）：qreg50 两窗口均优于 ridge、52 周显著（p≈0.015）；gbm 排名在两个窗口
  之间大幅翻转（不稳定）；市场因子显著略差；收缩方向一致有效。Ridge 与快照预测交叉验证一致（2e-16）。
- 研究结论供 Week 5 提交决策（选项 A 保留 ridge / 选项 B 事前修订为 qreg50，二选一，须全组在提交前确定）。

## 2026-10-17（决策后）
- Week 5 **事前修订为 qreg50**：候选集加入 qreg50（`forecast.py` 同步更新），生成变体快照
  `weeks/week5/predictions_qreg50.csv`、`submission_qreg50.xlsx`、`params_qreg50.json`、`backtest_qreg50.csv` 等；
  v1 快照未做任何改动。修订记录：`weeks/week5/amendment_20261017.md`；本周报告：`weeks/week5/qreg50_weekly_report.md`。
- `ledger.md` 追加修订记录（只增不改）。
- README 重写：每周历史、复现指南、已知问题与注意事项。
- 注：本机无 git 远程与凭据，未能 push；已生成 `DASE7310_GP1_Repo.bundle` 便于迁移/推送（见仓库外说明）。

