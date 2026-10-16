# SETUP：环境与数据（可复现说明）

本文件说明如何从零恢复本 repo 的运行环境与数据。

## 1. 重建 Python 环境（conda）

- 本机环境：Miniforge3（`C:\Users\Administrator\miniforge3`）→ 环境 **`dase7310`**（Python **3.12.15**）。
- 精确导出（含构建号与 pip 包版本）：
  - `environment.yml` —— 完整 conda + pip 清单（**推荐**：`conda env create -f environment.yml`）；
  - `environment_explicit.txt` —— 全部包的精确下载 URL 列表（`conda create -n dase7310 --file environment_explicit.txt` 后
    再按 `environment.yml` 的 `pip:` 段安装 pip 包）。
- 关键依赖：akshare 1.19.1、pandas 3.0.6、numpy 2.5.3、scikit-learn 1.9.1、statsmodels 0.15.0、openpyxl、yfinance（历史脚本用）。

## 2. ⚠️ 必须的运行时设置（本机环境缺陷绕行）

`dase7310` 环境同时装了 MKL 2026 与 llvm-openmp，**直接跑 sklearn 会原生崩溃（无提示，退出码 0xC06D007F）**。
所有涉及拟合的命令前都先执行：

```powershell
$env:MKL_THREADING_LAYER = 'SEQUENTIAL'
```

（若在别的机器重建环境后没有该症状，可省略。）

## 3. 数据（全部随 git 提交，复现无需联网）

| 文件 | 内容 |
|---|---|
| `data/daily_closes.csv` | 十股 **新浪后复权（hfq）** 日收盘（long 格式，2022-10-02 起） |
| `data/weekly_closes.csv` / `weekly_returns.csv` | W-FRI 周收盘 / 周收益 |
| `data/index_closes.csv` / `index_returns.csv` | 恒指、恒生科技周数据 |
| `data/meta.json` | 数据来源（Sina Finance）、下载时间（vintage）、最后交易日 |
| `research/*_long.csv` | 研究实验用长历史（2019-12 起，另一批次） |

- **vintage（数据版本）**：以 `data/meta.json` 的 `refresh_time` 为准（当前批次：2026-10-16 下载，最后交易日 10-16）。
- **复现快照时不要先联网刷新**：`snapshot`/`backtest`/`evaluate` 都只读 `data/`，保持批次一致即可完全复现历史输出。
- **独立备份**：仓库外还有 `..\数据存档_20261017\`（同批次 CSV + `SHA256.txt` 校验），可离线复制恢复：
  将它拷回 `data/` 并核对哈希即可。

## 4. 数据源与 fallback（可配置）

`refresh-data` 的整批取数规则（不允许同一批混源）：

```powershell
& $py forecast.py refresh-data                 # 默认 auto：东财整批 → 任一失败切新浪整批（保留历史口径）
& $py forecast.py refresh-data --source sina   # 强制新浪（本机网络下东财被拒时推荐，速度快）
& $py forecast.py refresh-data --source eastmoney  # 强制东财（不可用即失败，供对比测试）
```

- 每个来源重试 2 次（间隔 2 秒）；同一来源内任一股票数据无效 → 整批放弃该来源；
- 校验：非空、有限、正数、日期不重复；全失败时报错并保留最后异常（不会静默出坏数据）；
- 指数（HSI/HSTECH）：新浪优先，东财兜底；两者都失败 → 自动停用 `ridge_mkt` 候选（其余功能不受影响）；
- 结果来源与偏好记录在 `data/meta.json`（`source` / `source_preference` / `index_source`）。

## 5. 快速自检（smoke test）

```powershell
$env:MKL_THREADING_LAYER='SEQUENTIAL'
& $py forecast.py backtest --cutoff 2026-10-16     # 应打印候选表（qreg50 为可提交候选中最优）
& $py forecast.py snapshot --cutoff 2026-10-16 --week week5 --variant _qreg50
# 第 2 条的输出应与 weeks/week5/predictions_qreg50.csv 完全一致（含 qreg50 alpha=0.001）
```

## 6. 其他说明

- git：本机装在 `C:\Users\Administrator\miniforge3\Library\bin\git.exe`（base 环境）；任意 git ≥2.40 均可。
- 读取 PDF/文档的环境（可选，仅分析用）：系统 Python 3.12（`C:\Users\Administrator\AppData\Local\Programs\Python\Python312`）装有 PyMuPDF。
- 网络受限环境的已知情况：东方财富接口部分网络会直接拒绝连接（ConnectionError）→ 用 `--source sina` 或让其自动切换。
