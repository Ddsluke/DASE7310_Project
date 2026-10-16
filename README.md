# DASE7310 GP1 - 周收益率预测 repo

十个港股（9988 阿里、0066 港铁、1398 工行、3988 中行、0981 中芯、0005 汇丰、1810 小米、0016 新鸿基、1113 长实、0700 腾讯）
的**周收益率**预测项目。课程评分 = 每周十股 `|预测 − 实际|` 之和（越小越好）；共 5 轮 Moodle 提交。

本 repo 是小组的**唯一预测流水线 + 全部研究记录**：
单一脚本（`forecast.py`）+ 每周不可追改快照（`weeks/weekN/`）+ 研究实验台（`research/`）+ 周度台账（`ledger.md`）。

> 政策：**只增不改**。每周提交值与实际结果的记录一旦生成不得修改；更正/修订以"新增文件 + 修订说明"留痕（见 `weeks/week5/amendment_20261017.md` 示例）。

---

## 一、每周历史（我们做了什么）

| 周 | 提交日 | 截点（数据截至） | 目标周 | 提交模型 | 实际表现（复算） | 备注 |
|---|---|---|---|---|---|---|
| W1 | 09-20 | 09-18 | 09-21~25 | 20 周中位数（yfinance 未复权） | MAE 1.8437pp / 方向 5/10 | 原始脚本在归档目录；口径与后续不同，仅留证 |
| W2 | 09-27 | 09-25 | 09-28~10-02 | AR（BIC 选阶，全为 AR(1)） | MAE 2.6139pp / 方向 2/10 | 与当时对照 PDF 完全一致（口径校验通过） |
| W3 | 10-04 | 10-02 | 10-05~09 | Pooled Ridge（7 特征+哑变量，156 周/8 周调参） | MAE 2.4186pp / 方向 4/10 | 重建管道 0 误差复现提交值 |
| W4 | 10-11 | 10-09 | 10-12~16 | **实际提交 = Week 3 的数值**（组员操作失误，未重跑） | MAE 2.2899pp / 方向 3/10 | 双轨留证：`submitted_values.csv`（实际）与 `predictions.csv`（正确重建，MAE 2.1179） |
| W5 | 10-18（计划） | 10-16 | 10-19~23 | **qreg50**（中位数回归；修订候选，见下） | 待目标周结束后 `evaluate` | v1 快照为 ridge（保留）；最终提交 = `predictions_qreg50.csv` |

关键事件与教训（报告素材）：

- **W4 事故**：提交文件直接沿用了 W3 的 10 个预测值（还配了"Week 4 正式结果"的标题）。我们以 week3 管线在正确的 10-09 截止重跑复现出"本应结果"，两套数值双轨建档；正确版的 MAE（2.1179）低于误提交版（2.2899）。
- **W4 代码缺陷**（当时那份 docx 简版）：`tail(156*10)` 在按股票排序的表上截取只会覆盖约 8 只股票，配合 `OneHotEncoder(handle_unknown='error')` 会在预测时报未知类别错误（本机已复现）。W5 起因统一使用 `forecast.py`。
- **W5 修订**：预注册候选（HSI/HSTECH 市场因子、Ridge+20 周均值 50/50 组合）在同口径检验中均未达标（前者还显著更差），被规则拒绝；一个**新候选 qreg50**（与评分口径一致的中位数回归）在两个冻结窗口都优于 ridge，其中 52 周显著（p≈0.015），于是在目标周开始前做了**事前修订**并据此提交。
- **研究结论**（五页报告"潜在改进"见 `research/REPORT_NOTES.md`）：周频收益可预测成分接近零；"让损失函数与评分口径一致"是目前最稳健的改进方向；非线性（树模型）、市场因子、组合平均均未通过检验——且 20 周窗口会把偶然进步放大成"最好模型"（树模型在 20 周排第 1、52 周排第 15）。

## 二、目录结构

```
forecast.py           唯一提交脚本：refresh-data / backtest / snapshot / evaluate
data/                 数据缓存（hfq 日/周收盘、周收益、HSI/HSTECH、meta.json）
weeks/week1..week5/   每周快照（见下）
research/             研究实验台：16 候选同口径对比、显著性检验、qreg50 深度报告
ledger.md             周度台账（提交值、实际误差、失败速记；只增不改）
CHANGELOG.md          变更记录
归档_*（repo 外）      原代码只读归档（含 SHA256），旧驱动脚本未做任何修改
```

每周快照文件说明（W5 以 `_qreg50` 变体为例）：

| 文件 | 含义 |
|---|---|
| `predictions[_qreg50].csv` | **当周提交值（4 位小数）** |
| `submission[_qreg50].xlsx` | 同内容的 Excel（Moodle 用） |
| `params[_qreg50].json` | 截点/数据源/候选/选择规则/被选模型/参数 |
| `backtest[_qreg50].csv` + `backtest_detail[_qreg50].csv` | 冻结窗口（最近 20 个已知目标周）回测汇总与逐股明细 |
| `report[_qreg50].md` | 自动生成的快照说明 |
| `realized*.csv`（期末追加） | 目标周结束后的实际收益与逐股误差（**不得回填进 predictions**） |
| `amendment_..md` / 专题报告 | 修订记录与周报 |

## 三、冻结口径与决策规则

- **数据**：AkShare；整批优先东方财富、失败整批切新浪；**后复权 hfq** 日收盘；周=W-FRI 最后已实现收盘价；`r = P_t/P_{t-1} − 1`。
- **模型族**：基准（mean20 / median20 / ewma85 / naive / zero）、Ridge 族（ridge / ridge100 / ridge_mkt）、组合（combo50）、**qreg50（中位数回归）**。
  - 共同协议：最近 **156** 个已知目标周训练（十股合并）；更早 **8** 个已知目标周上调参（ridge: α∈{1,10,100}；qreg50: α∈{0.001,0.01,0.1}）。
- **评价窗口**：截点前最近 **20** 个已知目标周（十股同窗、同口径）。
- **选择规则（预注册，生成快照时固定）**：combo50 仅在同时优于两个成分且赢 ≥5/10 只股票时合格；ridge_mkt 仅在优于 ridge 时合格；
  在合格候选中取窗口总绝对误差最小者提交；zero 仅作参考不计入候选。
- **修订流程**：候选集/规则的任何修订必须在目标周**开始前**完成，并写入新增修订文件（示例：`weeks/week5/amendment_20261017.md`）。

## 四、复现指南

环境（本机）：Miniforge3 → 环境 `dase7310`（Python 3.12，含 akshare / pandas / numpy / scikit-learn / statsmodels / openpyxl）。
**运行 sklearn 相关命令前必须设置**（该环境 MKL 与 llvm-openmp 冲突）：

```powershell
$env:MKL_THREADING_LAYER = 'SEQUENTIAL'
$py = 'C:\Users\Administrator\miniforge3\envs\dase7310\python.exe'
```

### 4.1 每周标准流程

```powershell
# 1) 拉取最新数据（写到 data/，含 HSI/HSTECH）
& $py forecast.py refresh-data

# 2) 只回测（不动任何快照文件）
& $py forecast.py backtest --cutoff 2026-10-16

# 3) 生成当周快照（新的一周用 --week weekN；变体用 --variant 防覆盖）
& $py forecast.py snapshot --cutoff 2026-10-16 --week week5 --variant _qreg50

# 4) 目标周结束后记录实际值
& $py forecast.py evaluate --week week4                                   # 按该周 predictions.csv
& $py forecast.py evaluate --week week4 --values weeks\week4\submitted_values.csv --suffix submitted
& $py forecast.py evaluate --week week5 --values weeks\week5\predictions_qreg50.csv --suffix qreg50
```

### 4.2 复现历史各周

- **W2 / W3**：`weeks/week2|week3/predictions.csv` 为当时提交值（从归档的 `week2_results.xlsx`、`week3_ridge_results.xlsx` 转录），
  `& $py forecast.py evaluate --week week2|week3` 即可复算实际 MAE（W2 = 2.6139、W3 = 2.4186，与当时报告一致）。
- **W4**：`submitted_values.csv`（实际提交，=W3 值）与 `predictions.csv`（按 week3 管线在 10-09 截止的正确重建）。
  重建的等价性验证：用 10-02 截止重跑可 **0 误差**复现 W3 提交值（见 `weeks/week4/report.md`）。
- **W5**：`snapshot --cutoff 2026-10-16 --week week5 --variant _qreg50` 可完整重跑出 `predictions_qreg50.csv`。
- **W1**：原脚本使用 yfinance 未复权数据，口径特殊；快照仅作档案（`weeks/week1/README 语境见 params.json`）。

### 4.3 研究实验（qreg50 的证据来源）

```powershell
& $py research\compare_models.py     # 首次会拉取 2020 起的长历史（research/*_long.csv）
```
产出：`research/results_20w.csv`、`results_52w.csv`、`significance_52w.csv`、`backtest_detail_*.csv`；
解读与报告文本：`research/REPORT_NOTES.md`、`research/qreg50_report.md`。

### 4.4 git 历史（对应每周动作）

```
scaffold → data → weeks(week1-3) → week4(双轨) → week5(ridge 快照) → ledger
→ week5 addendum(AR 组合检验) → research(16 候选实验) → qreg50 报告 → week5 qreg50 修订提交
```
每次改动一个逻辑提交；推送远程请见仓库根目录说明（或联系 owner 获取 bundle）。

## 五、已知问题与注意事项

1. **本机 MKL/llvm-openmp 冲突**：任何 sklearn 命令前加 `$env:MKL_THREADING_LAYER='SEQUENTIAL'`（症状：无提示原生崩溃）。
2. **东方财富接口在本网络被拒**（ConnectionError），流水线自动整批切新浪——与 W2/W3 保存记录一致，不影响口径。
3. **W4 事故教训**：提交前逐项核对（截点正确、数字与文件一致、Moodle 真上传成功）；repo 的 `ledger.md` 负责登记。
4. **口径**：W1 未复权 vs W2+ hfq；跨周 MAE 不可直接排名（不同窗口/口径），同窗对比才有效。
