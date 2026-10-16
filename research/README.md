# research/ — 研究实验台（不是提交流水线）

本目录用于**回答"为什么保留 Ridge"以及系统测试"新方案"**，供五页报告与展示使用。
提交流水线仍为 repo 根目录的 `forecast.py`；本目录的任何结果都不会回改已生成的周快照。

## 协议（与提交流水线完全一致）

- 数据：Sina 港股价 hfq 日线（本目录扩展至 2019-12 起，以便做更长评估窗）；W-FRI 周收益。
- 训练：最近 156 个已知目标周（十股合并）；调参：更早 8 个已知目标周；只使用 origin 之前信息。
- 评估窗：最近 **20 周**（与 Week5 快照同窗，用于交叉验证）与最近 **52 周**（长窗稳健性）。

## 候选一览

| 候选 | 类型 | 说明 |
|---|---|---|
| zero / mean20 / median20 / ewma85 / naive | 基准 | 全零、20 周均值/中位数、EWMA(λ=0.85)、上周值 |
| ridge | 提交流水线模型 | Pooled Ridge，α 在 {1,10,100} 调参 |
| ridge100 | Ridge 变体 | 固定强收缩 α=100 |
| ridge_mkt | 市场因子 | +HSI/HSTECH 滞后周收益（预注册候选②） |
| combo50_m20 / combo50_ar | 组合 | 0.5×Ridge + 0.5×(20 周均值 / AR)，预注册候选① |
| shrunk50 | 收缩 | 0.5×Ridge（研究用） |
| ensemble4 | 集成 | (mean20+median20+ewma85+ridge)/4 |
| **qreg50** | **新方案** | 分位数回归（q=0.5，L1 目标，与评分口径一致），α∈{0.001,0.01,0.1} 同协议调参 |
| **huber** | **新方案** | Huber 稳健回归（抗离群） |
| **winsor_ridge** | **新方案** | 特征按训练窗 2%/98% 分位截尾再 Ridge |
| **gbm** | **新方案** | 直方图梯度提升（sklearn HGB，树模型/LightGBM 思路的替代） |

## 显著性检验

`significance_52w.csv`：以**周**为 block 的配对 bootstrap（4000 次重采样，防同日相关高估显著性）：
差值 = |误差_X| − |误差_Ridge|（正 = Ridge 更好），给出 95% CI 与"Ridge 更好的重采样占比"。

## 运行

```powershell
$env:MKL_THREADING_LAYER='SEQUENTIAL'
& C:\Users\Administrator\miniforge3\envs\dase7310\python.exe compare_models.py
```

（首次运行会拉取长历史数据存入本目录；`*_long.csv` 已随 repo 提交。）
