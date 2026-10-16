"""研究实验台（不是提交流水线）：在完全相同的协议下对比 Ridge 与一批"新方案"。

协议与提交流水线一致：156 周滚动训练、8 周窗口调参、W-FRI 周收益、Sina hfq。
评估窗口：最近 20 周（与 Week5 快照同窗）与最近 52 周（长窗稳健性）。
新候选：分位数回归(中位数, L1目标)、Huber、Winsorized Ridge、直方图梯度提升(树模型)、
        多模型等权集成、收缩版 Ridge。
另做：以周为 block 的配对 bootstrap 显著性检验（Ridge vs 各主要候选）。
输出：results_20w.csv / results_52w.csv / significance_52w.csv / backtest_detail_long.csv
"""
import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import forecast as fc  # noqa: E402

from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.linear_model import HuberRegressor, QuantileRegressor  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import OneHotEncoder  # noqa: E402
from statsmodels.tsa.ar_model import AutoReg  # noqa: E402

R = Path(__file__).resolve().parent
CUTOFF = pd.Timestamp("2026-10-16")
LONG_START = "2019-12-01"
QREG_ALPHAS = [0.001, 0.01, 0.1]


# --------------------------------------------------------------- long data
def fetch_long():
    import akshare as ak

    px = {}
    for code in fc.STOCKS:
        d = ak.stock_hk_daily(symbol=code.zfill(5), adjust="hfq")
        d = d.rename(columns={"日期": "date", "收盘": "close"})
        d["date"] = pd.to_datetime(d["date"])
        d = d[["date", "close"]].sort_values("date")
        d = d[d["date"].between(LONG_START, CUTOFF)]
        px[code] = d.set_index("date")["close"]
        print(f"fetched {code}: {len(d)} rows, last {d['date'].max().date()}", flush=True)
    closes = pd.DataFrame(px)
    closes = closes.resample("W-FRI").last()
    returns = closes.pct_change(fill_method=None)
    closes.to_csv(R / "weekly_closes_long.csv")
    returns.to_csv(R / "weekly_returns_long.csv")

    idx = {}
    for sym, name in [("HSI", "hsi"), ("HSTECH", "hstech")]:
        d = ak.stock_hk_index_daily_sina(symbol=sym)
        d = d.rename(columns={"日期": "date", "收盘": "close"})
        d["date"] = pd.to_datetime(d["date"])
        d = d[["date", "close"]].sort_values("date")
        d = d[d["date"].between(LONG_START, CUTOFF)]
        idx[name] = d.set_index("date")["close"]
    idx_closes = pd.DataFrame(idx).resample("W-FRI").last()
    idx_returns = idx_closes.pct_change(fill_method=None)
    idx_returns.to_csv(R / "index_returns_long.csv")
    (R / "meta_long.json").write_text(json.dumps(
        {"start": LONG_START, "end": str(CUTOFF.date()),
         "built": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2), encoding="utf-8")


# --------------------------------------------------------------- helpers
def forecast_ar(r: pd.Series) -> float:
    models = []
    for p in range(1, 5):
        try:
            models.append((p, AutoReg(r, lags=p, trend="c").fit()))
        except Exception:
            pass
    _, m = min(models, key=lambda x: x[1].bic)
    return float(m.predict(len(r), len(r)).iloc[0])


def qreg_pipeline(alpha, features):
    prep = ColumnTransformer([
        ("num", fc.StandardScaler(), features),
        ("stock", OneHotEncoder(handle_unknown="error", sparse_output=False), ["stock_code"]),
    ])
    return make_pipeline(prep, QuantileRegressor(quantile=0.5, alpha=alpha, solver="highs"))


def qreg_predict(rows, asof):
    latest = fc.latest_rows(rows, asof)
    known = rows[(rows["target_week"] <= asof) & rows["y"].notna()]
    weeks = sorted(known["target_week"].unique())[-fc.TUNE_WEEKS:]
    losses = {}
    for al in QREG_ALPHAS:
        err = 0.0
        for week in weeks:
            earlier = fc.training_rows(rows, pd.Timestamp(week) - pd.Timedelta(days=7))
            valid = known[known["target_week"] == week]
            m = qreg_pipeline(al, fc.FEATURES).fit(earlier[fc.FEATURES + ["stock_code"]], earlier["y"])
            err += float(np.abs(m.predict(valid[fc.FEATURES + ["stock_code"]]) - valid["y"]).sum())
        losses[al] = err
    al = min(losses, key=losses.get)
    train = fc.training_rows(rows, asof)
    m = qreg_pipeline(al, fc.FEATURES).fit(train[fc.FEATURES + ["stock_code"]], train["y"])
    return dict(zip(fc.STOCKS, m.predict(latest[fc.FEATURES + ["stock_code"]])))


def huber_predict(rows, asof):
    latest = fc.latest_rows(rows, asof)
    train = fc.training_rows(rows, asof)
    prep = ColumnTransformer([
        ("num", fc.StandardScaler(), fc.FEATURES),
        ("stock", OneHotEncoder(handle_unknown="error", sparse_output=False), ["stock_code"]),
    ])
    m = make_pipeline(prep, HuberRegressor(epsilon=1.35, alpha=1e-4, max_iter=1000))
    m.fit(train[fc.FEATURES + ["stock_code"]], train["y"])
    return dict(zip(fc.STOCKS, m.predict(latest[fc.FEATURES + ["stock_code"]])))


def winsor_ridge_predict(rows, asof, alpha=fc.ALPHAS[0]):
    train = fc.training_rows(rows, asof).copy()
    latest = fc.latest_rows(rows, asof).copy()
    lo = train[fc.FEATURES].quantile(0.02)
    hi = train[fc.FEATURES].quantile(0.98)
    for df in (train, latest):
        df[fc.FEATURES] = df[fc.FEATURES].clip(lo, hi, axis=1)
    m = fc.ridge_model(alpha, fc.FEATURES).fit(train[fc.FEATURES + ["stock_code"]], train["y"])
    return dict(zip(fc.STOCKS, m.predict(latest[fc.FEATURES + ["stock_code"]])))


def gbm_predict(rows, asof):
    latest = fc.latest_rows(rows, asof)
    train = fc.training_rows(rows, asof)
    prep = ColumnTransformer([
        ("num", "passthrough", fc.FEATURES),
        ("stock", OneHotEncoder(handle_unknown="error", sparse_output=False), ["stock_code"]),
    ])
    m = make_pipeline(prep, HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=40,
        l2_regularization=1.0, random_state=0))
    m.fit(train[fc.FEATURES + ["stock_code"]], train["y"])
    return dict(zip(fc.STOCKS, m.predict(latest[fc.FEATURES + ["stock_code"]])))


def candidates_at(rows, returns, idx_ret, asof):
    up = returns[returns.index <= asof]
    mean20 = {c: float(up[c].tail(20).mean()) for c in fc.STOCKS}
    median20 = {c: float(up[c].tail(20).median()) for c in fc.STOCKS}
    ewma = {c: float(up[c].ewm(alpha=1 - fc.EWMA_LAMBDA, adjust=False).mean().iloc[-1]) for c in fc.STOCKS}
    naive = {c: float(up[c].iloc[-1]) for c in fc.STOCKS}
    out = {"zero": {c: 0.0 for c in fc.STOCKS}, "mean20": mean20, "median20": median20,
           "ewma85": ewma, "naive": naive}
    ridges = {}
    for name, feats, alpha in [("ridge", fc.FEATURES, None), ("ridge100", fc.FEATURES, 100.0),
                               ("ridge_mkt", fc.FEATURES + fc.MKT_FEATURES, None)]:
        try:
            p, _, _ = fc.ridge_predict(rows, asof, feats, alpha=alpha)
            out[name] = p
            ridges[name] = p
        except Exception as exc:
            print(f"  ! {name} failed at {asof.date()}: {exc}", flush=True)
    r = ridges["ridge"]
    ar = {c: forecast_ar(up[c].dropna()) for c in fc.STOCKS}
    out["combo50_m20"] = {c: 0.5 * r[c] + 0.5 * mean20[c] for c in fc.STOCKS}
    out["combo50_ar"] = {c: 0.5 * r[c] + 0.5 * ar[c] for c in fc.STOCKS}
    out["shrunk50"] = {c: 0.5 * r[c] for c in fc.STOCKS}
    out["ensemble4"] = {c: (mean20[c] + median20[c] + ewma[c] + r[c]) / 4 for c in fc.STOCKS}
    for name, fn in [("qreg50", qreg_predict), ("huber", huber_predict),
                     ("winsor_ridge", winsor_ridge_predict), ("gbm", gbm_predict)]:
        t0 = time.time()
        try:
            out[name] = fn(rows, asof)
        except Exception as exc:
            print(f"  ! {name} failed at {asof.date()}: {exc}", flush=True)
        print(f"    {name} @ {asof.date()} done in {time.time()-t0:.1f}s", flush=True)
    return out


def run_window(rows, returns, idx_ret, weeks_n, label):
    known = rows[(rows["target_week"] <= CUTOFF) & rows["y"].notna()]
    targets = [pd.Timestamp(w) for w in sorted(known["target_week"].unique())[-weeks_n:]]
    print(f"== window {label}: {targets[0].date()} ~ {targets[-1].date()} ({len(targets)} weeks) ==", flush=True)
    y_map = returns.stack()
    records = []
    for i, t in enumerate(targets):
        asof = t - pd.Timedelta(days=7)
        print(f"[{label}] {i+1}/{len(targets)} target {t.date()}", flush=True)
        preds = candidates_at(rows, returns, idx_ret, asof)
        actual = {c: float(y_map.loc[(t, c)]) for c in fc.STOCKS}
        for cand, p in preds.items():
            for c in fc.STOCKS:
                records.append({"window": label, "candidate": cand, "target_week": t, "stock_code": c,
                                "pred": p[c], "actual": actual[c], "abs_err": abs(p[c] - actual[c])})
    detail = pd.DataFrame(records)
    summary = detail.groupby("candidate")["abs_err"].agg(
        total_abs_error="sum", mae_pp=lambda s: s.mean() * 100).reset_index()
    hits = {}
    for cand, g in detail.groupby("candidate"):
        hits[cand] = int((np.sign(g["pred"]) == np.sign(g["actual"])).sum())
    summary["direction_hits"] = summary["candidate"].map(hits)
    summary = summary.sort_values("total_abs_error").reset_index(drop=True)
    summary.to_csv(R / f"results_{label}.csv", index=False)
    return summary, detail


def significance(detail52):
    """以周为 block 的配对 bootstrap：diff = |err_ridge| - |err_X|（正=ridge 更差）。"""
    ridge = detail52[detail52["candidate"] == "ridge"].set_index(["target_week", "stock_code"])["abs_err"]
    weeks = sorted(detail52["target_week"].unique())
    rng = np.random.default_rng(20261017)
    rows_out = []
    for cand in sorted(detail52["candidate"].unique()):
        if cand == "ridge":
            continue
        other = detail52[detail52["candidate"] == cand].set_index(["target_week", "stock_code"])["abs_err"]
        other = other.reindex(ridge.index)
        diff = other - ridge  # X - ridge; 正 = ridge 更好
        by_week = diff.groupby(level=0)
        week_diffs = [by_week.get_group(w).to_numpy() for w in weeks]
        means = []
        for _ in range(4000):
            pick = rng.integers(0, len(weeks), len(weeks))
            sample = np.concatenate([week_diffs[j] for j in pick])
            means.append(sample.mean())
        means = np.array(means)
        lo, hi = np.percentile(means, [2.5, 97.5])
        p_ridge_better = float((means > 0).mean())
        wins = int((diff > 0).sum())
        rows_out.append({"candidate_vs_ridge": cand, "mean_diff_pp": float(diff.mean() * 100),
                         "ci95_low_pp": float(lo * 100), "ci95_high_pp": float(hi * 100),
                         "p_ridge_better": p_ridge_better, "stock_week_wins_ridge": wins, "n": int(len(diff))})
    sig = pd.DataFrame(rows_out).sort_values("mean_diff_pp")
    sig.to_csv(R / "significance_52w.csv", index=False)
    return sig


if __name__ == "__main__":
    if not (R / "weekly_returns_long.csv").exists():
        fetch_long()
    returns = pd.read_csv(R / "weekly_returns_long.csv", index_col=0, parse_dates=True)
    idx_ret = pd.read_csv(R / "index_returns_long.csv", index_col=0, parse_dates=True)
    rows = fc.feature_rows(returns, idx_ret)

    s20, d20 = run_window(rows, returns, idx_ret, 20, "20w")
    print(s20.round(6).to_string(index=False), flush=True)
    s52, d52 = run_window(rows, returns, idx_ret, 52, "52w")
    print(s52.round(6).to_string(index=False), flush=True)
    d20.to_csv(R / "backtest_detail_20w.csv", index=False)
    d52.to_csv(R / "backtest_detail_52w.csv", index=False)

    print("== significance (52w, block bootstrap by week) ==", flush=True)
    sig = significance(d52)
    print(sig.round(4).to_string(index=False), flush=True)

    # sanity: research ridge vs submission snapshot ridge on the shared 20-week window
    snap = pd.read_csv(REPO / "weeks/week5/backtest_detail.csv", parse_dates=["target_week"], dtype={"stock_code": str})
    snap_r = snap[snap["candidate"] == "ridge"].set_index(["target_week", "stock_code"])["pred"]
    res_r = d20[d20["candidate"] == "ridge"].set_index(["target_week", "stock_code"])["pred"]
    common = snap_r.index.intersection(res_r.index)
    print(f"sanity: ridge pred rows matched={len(common)}, max abs diff={float((snap_r.loc[common] - res_r.loc[common]).abs().max()):.2e}", flush=True)
    print("done", flush=True)
