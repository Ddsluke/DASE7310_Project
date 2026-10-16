# -*- coding: utf-8 -*-
"""DASE7310 GP1 - 单一脚本预测流水线（single-script pipeline）

用法（在 repo 根目录、使用 dase7310 环境）:
    python forecast.py refresh-data
    python forecast.py backtest  --cutoff 2026-10-16
    python forecast.py snapshot  --cutoff 2026-10-16 --week week5
    python forecast.py evaluate  --week week4
    python forecast.py evaluate  --week week4 --values weeks/week4/submitted_values.csv --suffix submitted

约定（冻结口径，2026-10-16 起）:
- 数据源: AkShare；整批优先东方财富，失败则整批切换新浪财经；后复权(hfq)日收盘价。
- 周收益: 每周 W-FRI 最后一根已实现收盘价，r[t] = P[t]/P[t-1] - 1。
- Ridge: 7 个自身特征 + 股票哑变量；训练=最近 156 个已知目标周（10 股合并）；
  正则 alpha 在更早的 8 个已知目标周上用绝对误差从 {1,10,100} 中选择；
  ridge_mkt 额外加入上一已完成周的恒指/恒生科技周收益（hsi_lag1, hstech_lag1）。
- 冻结回测窗口: 截止日前最近 20 个已知目标周（十股同一窗口）。
- 提交模型选择（预注册规则，生成快照时即固定，之后不得追改）:
    * 可提交候选: mean20, median20, ewma85, naive, ridge, ridge100, combo50, ridge_mkt, qreg50
    * combo50 = 0.5*ridge + 0.5*mean20；仅当窗口总绝对误差同时低于两个成分、
      且相对更优成分至少赢在 5/10 只股票上时，才算合格候选。
    * ridge_mkt 仅当窗口总绝对误差低于 ridge 时才算合格候选。
    * 在合格候选中选窗口总绝对误差最小者；zero（全零）只作参考展示，不作为提交候选。
- 2026-10-17 事前修订（追加记录，未改动任何既有快照；见 weeks/week5/amendment_20261017.md）:
    * 候选集加入 **qreg50**（中位数回归 / 分位数回归 q=0.5；与 ridge 同特征、同协议，仅损失函数
      为绝对值+L1），依据：与课程"绝对误差"评分口径一致，20 周 / 52 周双窗口均优于 ridge。
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import QuantileRegressor, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# ----------------------------------------------------------------------------- path & constants
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
WEEKS = HERE / "weeks"

STOCKS = ["9988", "0066", "1398", "3988", "0981", "0005", "1810", "0016", "1113", "0700"]
START = "2022-10-02"
FEATURES = ["lag1", "lag2", "lag3", "mean4", "std4", "mean8", "std8"]
MKT_FEATURES = ["hsi_lag1", "hstech_lag1"]
ALPHAS = [1.0, 10.0, 100.0]
QREG_ALPHAS = [0.001, 0.01, 0.1]
TRAIN_WEEKS = 156
TUNE_WEEKS = 8
EVAL_WEEKS = 20
EWMA_LAMBDA = 0.85


def md_table(df: pd.DataFrame) -> str:
    """轻量 markdown 表格（避免依赖 tabulate）。"""
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append(f"{v:.6f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- data layer
def _fetch_stocks(start: str, end: str):
    """整批来源表决：优先 Eastmoney；任一股票失败则整批换 Sina。返回 (df, source)。"""
    import akshare as ak

    for source in ["Eastmoney", "Sina Finance"]:
        frames = []
        try:
            for code in STOCKS:
                if source == "Eastmoney":
                    d = ak.stock_hk_hist(symbol=code.zfill(5), period="daily", start_date=start.replace("-", ""),
                                         end_date=end.replace("-", ""), adjust="hfq")
                    d = d.rename(columns={"日期": "date", "收盘": "close"})
                else:
                    d = ak.stock_hk_daily(symbol=code.zfill(5), adjust="hfq")
                    d = d.rename(columns={"日期": "date", "收盘": "close"})
                d = d[["date", "close"]].copy()
                d["date"] = pd.to_datetime(d["date"])
                d["close"] = pd.to_numeric(d["close"], errors="raise")
                d = d[d["date"].between(start, end)].sort_values("date")
                if d.empty or not np.isfinite(d["close"]).all() or (d["close"] <= 0).any() or d["date"].duplicated().any():
                    raise ValueError(f"{code}: invalid prices from {source}")
                d["stock_code"] = code
                frames.append(d)
            return pd.concat(frames, ignore_index=True), source
        except Exception as exc:  # noqa: BLE001 - 整批切换来源
            print(f"[refresh] {source} failed: {type(exc).__name__}: {exc}")
    raise RuntimeError("Both data sources failed. No data refreshed.")


def _fetch_index(start: str, end: str):
    """恒指与恒生科技（新浪接口）。失败时返回 None（快照将自动停用 ridge_mkt）。"""
    import akshare as ak

    out = {}
    try:
        for sym, name in [("HSI", "hsi"), ("HSTECH", "hstech")]:
            d = ak.stock_hk_index_daily_sina(symbol=sym)
            d = d.rename(columns={"日期": "date", "收盘": "close"})
            d = d[["date", "close"]].copy()
            d["date"] = pd.to_datetime(d["date"])
            d["close"] = pd.to_numeric(d["close"], errors="raise")
            out[name] = d[d["date"].between(start, end)].sort_values("date")
    except Exception as exc:  # noqa: BLE001
        print(f"[refresh] index fetch failed: {type(exc).__name__}: {exc}")
        return None
    return out


def _weekly_last(daily: pd.DataFrame) -> pd.Series:
    return daily.set_index("date")["close"].resample("W-FRI").last()


def refresh_data(end: str | None = None):
    end = end or date.today().strftime("%Y-%m-%d")
    DATA.mkdir(parents=True, exist_ok=True)

    px, source = _fetch_stocks(START, end)
    wide = px.pivot(index="date", columns="stock_code", values="close")
    closes = wide.resample("W-FRI").last()
    closes = closes[STOCKS]
    returns = closes.pct_change(fill_method=None)

    idx = _fetch_index(START, end)
    idx_closes = idx_returns = None
    if idx is not None:
        idx_closes = pd.DataFrame({k: _weekly_last(v) for k, v in idx.items()})
        idx_returns = idx_closes.pct_change(fill_method=None)

    px.to_csv(DATA / "daily_closes.csv", index=False)
    closes.to_csv(DATA / "weekly_closes.csv")
    returns.to_csv(DATA / "weekly_returns.csv")
    if idx_closes is not None:
        idx_closes.to_csv(DATA / "index_closes.csv")
        idx_returns.to_csv(DATA / "index_returns.csv")

    meta = {
        "source": source,
        "requested_start": START,
        "requested_end": end,
        "refresh_time": datetime.now().isoformat(timespec="seconds"),
        "last_daily_date": {c: str(px[px.stock_code == c]["date"].max().date()) for c in STOCKS},
        "index_source": "Sina Finance (stock_hk_index_daily_sina)" if idx is not None else None,
        "index_last_date": ({k: str(v["date"].max().date()) for k, v in idx.items()} if idx is not None else None),
    }
    (DATA / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[refresh] stocks: {source}, weekly rows {len(closes)}, last weekly {closes.index[-1].date()}")
    if idx_closes is not None:
        print(f"[refresh] indexes: rows {len(idx_closes)}, last {idx_closes.index[-1].date()}")
    return meta


def load_data():
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    returns = pd.read_csv(DATA / "weekly_returns.csv", index_col=0, parse_dates=True)
    closes = pd.read_csv(DATA / "weekly_closes.csv", index_col=0, parse_dates=True)
    idx_ret = None
    if (DATA / "index_returns.csv").exists():
        idx_ret = pd.read_csv(DATA / "index_returns.csv", index_col=0, parse_dates=True)
    return closes, returns, idx_ret, meta


# ----------------------------------------------------------------------------- feature table
def feature_rows(returns: pd.DataFrame, idx_ret: pd.DataFrame | None = None) -> pd.DataFrame:
    frames = []
    for code in STOCKS:
        r = returns[code].dropna()
        f = pd.DataFrame({
            "asof": r.index, "stock_code": code,
            "lag1": r, "lag2": r.shift(1), "lag3": r.shift(2),
            "mean4": r.rolling(4).mean(), "std4": r.rolling(4).std(),
            "mean8": r.rolling(8).mean(), "std8": r.rolling(8).std(),
            "y": r.shift(-1),
        })
        f["target_week"] = f["asof"] + pd.Timedelta(days=7)
        if idx_ret is not None:
            f = f.merge(idx_ret[["hsi", "hstech"]].rename(columns={"hsi": "hsi_lag1", "hstech": "hstech_lag1"}),
                        left_on="asof", right_index=True, how="left")
        frames.append(f)
    rows = pd.concat(frames, ignore_index=True)
    return rows.dropna(subset=FEATURES)


# ----------------------------------------------------------------------------- models
def ridge_model(alpha: float, features: list[str]):
    prep = ColumnTransformer([
        ("num", StandardScaler(), features),
        ("stock", OneHotEncoder(handle_unknown="error", sparse_output=False), ["stock_code"]),
    ])
    return make_pipeline(prep, Ridge(alpha=alpha))


def training_rows(rows: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    known = rows[(rows["target_week"] <= asof) & rows["y"].notna()]
    weeks = sorted(known["target_week"].unique())[-TRAIN_WEEKS:]
    if len(weeks) != TRAIN_WEEKS:
        raise ValueError("Insufficient history for 156-week training window")
    return known[known["target_week"].isin(weeks)]


def latest_rows(rows: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    return rows[rows["asof"] == asof].set_index("stock_code").loc[STOCKS].reset_index()


def ridge_predict(rows: pd.DataFrame, asof: pd.Timestamp, features: list[str], alpha: float | None = None):
    """返回 (pred_series_dict, chosen_alpha, tune_losses)。alpha=None 时按 8 周滚动验证选择。"""
    rows = rows.dropna(subset=features)
    latest = latest_rows(rows, asof)
    if alpha is None:
        known = rows[(rows["target_week"] <= asof) & rows["y"].notna()]
        weeks = sorted(known["target_week"].unique())[-TUNE_WEEKS:]
        losses = {}
        for a in ALPHAS:
            error = 0.0
            for week in weeks:
                earlier = training_rows(rows, pd.Timestamp(week) - pd.Timedelta(days=7))
                valid = known[known["target_week"] == week]
                model = ridge_model(a, features).fit(earlier[features + ["stock_code"]], earlier["y"])
                error += float(np.abs(model.predict(valid[features + ["stock_code"]]) - valid["y"]).sum())
            losses[a] = round(error, 6)
        alpha = min(losses, key=losses.get)
    else:
        losses = {}
    train = training_rows(rows, asof)
    model = ridge_model(alpha, features).fit(train[features + ["stock_code"]], train["y"])
    pred = model.predict(latest[features + ["stock_code"]])
    return dict(zip(STOCKS, pred)), alpha, losses


def qreg_model(alpha: float, features: list[str]):
    """中位数回归（分位数 q=0.5）：与 ridge 同预处理，仅损失函数换为绝对值 + L1 惩罚。"""
    prep = ColumnTransformer([
        ("num", StandardScaler(), features),
        ("stock", OneHotEncoder(handle_unknown="error", sparse_output=False), ["stock_code"]),
    ])
    return make_pipeline(prep, QuantileRegressor(quantile=0.5, alpha=alpha, solver="highs"))


def qreg_predict(rows: pd.DataFrame, asof: pd.Timestamp):
    """qreg50 预测。返回 (pred_dict, chosen_alpha, tune_losses)。alpha 同协议在 8 周上调参。"""
    rows = rows.dropna(subset=FEATURES)
    latest = latest_rows(rows, asof)
    known = rows[(rows["target_week"] <= asof) & rows["y"].notna()]
    weeks = sorted(known["target_week"].unique())[-TUNE_WEEKS:]
    losses = {}
    for a in QREG_ALPHAS:
        error = 0.0
        for week in weeks:
            earlier = training_rows(rows, pd.Timestamp(week) - pd.Timedelta(days=7))
            valid = known[known["target_week"] == week]
            model = qreg_model(a, FEATURES).fit(earlier[FEATURES + ["stock_code"]], earlier["y"])
            error += float(np.abs(model.predict(valid[FEATURES + ["stock_code"]]) - valid["y"]).sum())
        losses[a] = round(error, 6)
    alpha = min(losses, key=losses.get)
    train = training_rows(rows, asof)
    model = qreg_model(alpha, FEATURES).fit(train[FEATURES + ["stock_code"]], train["y"])
    pred = model.predict(latest[FEATURES + ["stock_code"]])
    return dict(zip(STOCKS, pred)), alpha, losses


def simple_preds(returns: pd.DataFrame, cutoff: pd.Timestamp) -> dict[str, dict]:
    up = returns[returns.index <= cutoff]
    return {
        "mean20": {c: float(up[c].tail(20).mean()) for c in STOCKS},
        "median20": {c: float(up[c].tail(20).median()) for c in STOCKS},
        "ewma85": {c: float(up[c].ewm(alpha=1 - EWMA_LAMBDA, adjust=False).mean().iloc[-1]) for c in STOCKS},
        "naive": {c: float(up[c].iloc[-1]) for c in STOCKS},
        "zero": {c: 0.0 for c in STOCKS},
    }


# ----------------------------------------------------------------------------- backtest & selection
def frozen_targets(rows: pd.DataFrame, cutoff: pd.Timestamp) -> list[pd.Timestamp]:
    known = rows[(rows["target_week"] <= cutoff) & rows["y"].notna()]
    weeks = sorted(known["target_week"].unique())[-EVAL_WEEKS:]
    if len(weeks) != EVAL_WEEKS:
        raise ValueError("Insufficient known target weeks for the frozen window")
    return [pd.Timestamp(w) for w in weeks]


def backtest(rows: pd.DataFrame, returns: pd.DataFrame, cutoff: pd.Timestamp,
             idx_ret: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (summary, detail)。detail 列: candidate, target_week, stock_code, pred, actual, abs_err."""
    targets = frozen_targets(rows, cutoff)
    y_map = returns.stack()  # (asof, stock) -> return

    records = []
    alpha_history = []

    ridge_cache: dict[pd.Timestamp, dict] = {}
    ridge_mkt_cache: dict[pd.Timestamp, dict] = {}
    qreg_cache: dict[pd.Timestamp, dict] = {}
    for t in targets:
        asof = t - pd.Timedelta(days=7)
        p, a, losses = ridge_predict(rows, asof, FEATURES)
        ridge_cache[t] = p
        alpha_history.append({"target_week": str(t.date()), "alpha": a, "losses": losses})
        p100, _, _ = ridge_predict(rows, asof, FEATURES, alpha=100.0)
        ridge_cache[t]["_100"] = p100
        if idx_ret is not None:
            try:
                pm, am, _ = ridge_predict(rows, asof, FEATURES + MKT_FEATURES)
                ridge_mkt_cache[t] = pm
            except Exception as exc:  # noqa: BLE001
                print(f"[backtest] ridge_mkt unavailable at {t.date()}: {exc}")
        pq, qa, _ = qreg_predict(rows, asof)
        qreg_cache[t] = pq

    for t in targets:
        simple = simple_preds(returns, t - pd.Timedelta(days=7))
        preds = {
            "mean20": simple["mean20"], "median20": simple["median20"], "ewma85": simple["ewma85"],
            "naive": simple["naive"], "zero": simple["zero"],
            "ridge": ridge_cache[t], "ridge100": ridge_cache[t]["_100"],
            "qreg50": qreg_cache[t],
        }
        if t in ridge_mkt_cache:
            preds["ridge_mkt"] = ridge_mkt_cache[t]
        preds["combo50"] = {c: 0.5 * preds["ridge"][c] + 0.5 * preds["mean20"][c] for c in STOCKS}
        actual = {c: float(y_map.loc[(t, c)]) for c in STOCKS}
        for cand, p in preds.items():
            for c in STOCKS:
                records.append({"candidate": cand, "target_week": t, "stock_code": c,
                                "pred": p[c], "actual": actual[c], "abs_err": abs(p[c] - actual[c])})

    detail = pd.DataFrame(records)
    summary = (detail.groupby("candidate")
               .agg(total_abs_error=("abs_err", "sum"),
                    mae_pp=("abs_err", lambda s: s.mean() * 100),
                    direction_hits=("pred", lambda s: 0))
               .reset_index())
    hits = {}
    for cand, g in detail.groupby("candidate"):
        hits[cand] = int((np.sign(g["pred"]) == np.sign(g["actual"])).sum())
    summary["direction_hits"] = summary["candidate"].map(hits)
    summary = summary.sort_values("total_abs_error").reset_index(drop=True)
    summary.attrs["alpha_history"] = alpha_history
    return summary, detail


SUBMITTABLE = ["mean20", "median20", "ewma85", "naive", "ridge", "ridge100", "combo50", "ridge_mkt", "qreg50"]


def select_model(summary: pd.DataFrame, detail: pd.DataFrame) -> tuple[str, list[str]]:
    """预注册规则。返回 (chosen, eligible_list)。"""
    totals = dict(zip(summary["candidate"], summary["total_abs_error"]))

    def per_stock_wins(cand: str, comp: str) -> int:
        a = detail[detail["candidate"] == cand].set_index(["target_week", "stock_code"])["abs_err"]
        b = detail[detail["candidate"] == comp].set_index(["target_week", "stock_code"])["abs_err"]
        return int((a < b).sum())

    eligible = []
    notes = []
    if "combo50" in totals:
        better = min(totals["ridge"], totals["mean20"])
        if totals["combo50"] < better and min(per_stock_wins("combo50", "ridge"), per_stock_wins("combo50", "mean20")) >= 5:
            eligible.append("combo50")
        else:
            notes.append("combo50 未满足资格（未同时优于两个成分且至少赢 5/10 只股票）")
    if "ridge_mkt" in totals:
        if totals["ridge_mkt"] < totals["ridge"]:
            eligible.append("ridge_mkt")
        else:
            notes.append("ridge_mkt 未满足资格（未优于 ridge）")
    for cand in SUBMITTABLE:
        if cand in totals and cand not in ("combo50", "ridge_mkt") and totals[cand] == totals[cand]:
            eligible.append(cand)
    chosen = min(eligible, key=lambda c: totals[c])
    return chosen, eligible


def final_predictions(rows: pd.DataFrame, returns: pd.DataFrame, cutoff: pd.Timestamp,
                      chosen: str, idx_ret: pd.DataFrame | None = None):
    asof = cutoff
    if chosen in ("mean20", "median20", "ewma85", "naive", "zero"):
        return simple_preds(returns, cutoff)[chosen], None
    if chosen == "ridge":
        p, a, _ = ridge_predict(rows, asof, FEATURES)
        return p, a
    if chosen == "ridge100":
        p, _, _ = ridge_predict(rows, asof, FEATURES, alpha=100.0)
        return p, 100.0
    if chosen == "ridge_mkt":
        p, a, _ = ridge_predict(rows, asof, FEATURES + MKT_FEATURES)
        return p, a
    if chosen == "combo50":
        pr, a, _ = ridge_predict(rows, asof, FEATURES)
        sm = simple_preds(returns, cutoff)["mean20"]
        return {c: 0.5 * pr[c] + 0.5 * sm[c] for c in STOCKS}, a
    if chosen == "qreg50":
        p, a, _ = qreg_predict(rows, asof)
        return p, a
    raise ValueError(f"Unknown chosen model: {chosen}")


# ----------------------------------------------------------------------------- commands
def cmd_refresh(args):
    refresh_data(args.end)


def cmd_backtest(args):
    closes, returns, idx_ret, meta = load_data()
    rows = feature_rows(returns, idx_ret)
    cutoff = pd.Timestamp(args.cutoff)
    summary, detail = backtest(rows, returns, cutoff, idx_ret)
    pd.set_option("display.width", 200)
    print(f"[backtest] cutoff {cutoff.date()} | source {meta['source']} | "
          f"window {frozen_targets(rows, cutoff)[0].date()}..{frozen_targets(rows, cutoff)[-1].date()}")
    print(summary.round(6).to_string(index=False))
    chosen, eligible = select_model(summary, detail)
    print(f"[backtest] eligible: {eligible}\n[backtest] chosen per rule: {chosen}")


def cmd_snapshot(args):
    closes, returns, idx_ret, meta = load_data()
    rows = feature_rows(returns, idx_ret)
    cutoff = pd.Timestamp(args.cutoff)
    week_dir = WEEKS / args.week
    week_dir.mkdir(parents=True, exist_ok=True)

    summary, detail = backtest(rows, returns, cutoff, idx_ret)
    chosen, eligible = select_model(summary, detail)
    pred, alpha = final_predictions(rows, returns, cutoff, chosen, idx_ret)
    target = cutoff + pd.Timedelta(days=7)

    pred_df = pd.DataFrame({
        "stock_code": STOCKS,
        "moodle_value_4dp": [round(pred[c], 4) for c in STOCKS],
        "recommended_pct": [f"{pred[c] * 100:.2f}%" for c in STOCKS],
    })
    suffix = args.variant or ""
    pred_df.to_csv(week_dir / f"predictions{suffix}.csv", index=False)
    with pd.ExcelWriter(week_dir / f"submission{suffix}.xlsx", engine="openpyxl") as writer:
        pred_df.to_excel(writer, sheet_name="Moodle Submission", index=False)
    summary.round(6).to_csv(week_dir / f"backtest{suffix}.csv", index=False)
    detail.to_csv(week_dir / f"backtest_detail{suffix}.csv", index=False)

    params = {
        "week": args.week,
        "variant": args.variant or None,
        "cutoff": str(cutoff.date()),
        "target_friday": str(target.date()),
        "source": meta["source"],
        "data_meta": meta,
        "candidates": SUBMITTABLE,
        "selection_rule": "见 forecast.py 头注释；combo50/ridge_mkt 需先满足资格条件；在合格候选中取窗口总绝对误差最小",
        "eligible": eligible,
        "chosen_model": chosen,
        "ridge_alpha": alpha,
        "alpha_history": summary.attrs.get("alpha_history"),
        "backtest_window": [str(frozen_targets(rows, cutoff)[0].date()), str(frozen_targets(rows, cutoff)[-1].date())],
        "created_before_target_week": True,
        "amendment_note": ("候选集含 2026-10-17 事前修订加入的 qreg50；修订记录见 weeks/week5/amendment_20261017.md"
                           if args.variant else None),
        "note": "本快照在目标周实际收益未知时生成；生成后不得追改。实际收益请用 evaluate 命令另存 realized.csv。",
    }
    (week_dir / f"params{suffix}.json").write_text(json.dumps(params, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        f"# Week snapshot: {args.week}" + (f"（变体 {suffix.lstrip('_')}）" if suffix else ""),
        "",
        f"- 截止日（数据截点）: {cutoff.date()}　目标周五: {target.date()}",
        f"- 数据源: {meta['source']}（hfq）",
        f"- 冻结回测窗口: {params['backtest_window'][0]} ~ {params['backtest_window'][1]}（最近 {EVAL_WEEKS} 个已知目标周）",
        f"- 预注册选择规则选中的模型: **{chosen}**（合格候选: {', '.join(eligible)}）"
        + (f"；ridge alpha = {alpha}" if alpha is not None else ""),
        "- 生成时间在目标周结束之前；本记录不得追改。",
        "",
        "## 提交值（4 位小数）",
        md_table(pred_df),
        "",
        "## 候选模型冻结窗口回测（按总绝对误差升序）",
        md_table(summary.round(6)),
        "",
        "## 备注",
        "- zero 为参考基准，不参与提交候选。",
        "- 提交前请核对截点、源与 4 位小数。",
    ]
    (week_dir / f"report{suffix}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[snapshot] {args.week}{suffix}: chosen={chosen}, alpha={alpha}")
    print(pred_df.to_string(index=False))
    print(f"[snapshot] saved to {week_dir}")


def cmd_evaluate(args):
    week_dir = WEEKS / args.week
    params = json.loads((week_dir / "params.json").read_text(encoding="utf-8"))
    target = pd.Timestamp(params["target_friday"])
    values_file = Path(args.values) if args.values else week_dir / "predictions.csv"
    vals = pd.read_csv(values_file, dtype={"stock_code": str})
    if "moodle_value_4dp" in vals.columns:
        preds = dict(zip(vals["stock_code"], vals["moodle_value_4dp"]))
    else:
        preds = dict(zip(vals["stock_code"].astype(str), vals["recommended_pct"].str.rstrip("%").astype(float) / 100))

    closes, returns, idx_ret, meta = load_data()
    up = returns[returns.index <= target]
    actual, actual_dates, missing = {}, {}, []
    for c in STOCKS:
        ser = up[c].dropna()
        if len(ser) == 0 or ser.index[-1] != target:
            actual_dates[c] = str(ser.index[-1].date()) if len(ser) else None
            missing.append(c)
        else:
            actual_dates[c] = str(target.date())
        actual[c] = float(ser.iloc[-1])

    rows = []
    for c in STOCKS:
        p = float(preds[c])
        a = actual[c]
        rows.append({"stock_code": c, "pred": p, "actual": a, "abs_err_pp": abs(a - p) * 100,
                     "err_pp": (a - p) * 100, "actual_date": actual_dates[c],
                     "direction": "hit" if np.sign(a) == np.sign(p) else "miss"})
    res = pd.DataFrame(rows)
    suffix = f"_{args.suffix}" if args.suffix else ""
    res.to_csv(week_dir / f"realized{suffix}.csv", index=False)

    mae = res["abs_err_pp"].mean()
    rmse = float(np.sqrt((res["err_pp"] ** 2).mean()))
    hits = int((res["direction"] == "hit").sum())
    out = {"week": args.week, "target_friday": str(target.date()), "values_file": str(values_file),
           "n_missing_target_close": len(missing), "missing_stocks": missing,
           "total_abs_error": float(res["abs_err_pp"].sum() / 100), "mae_pp": float(mae),
           "rmse_pp": rmse, "direction_hits": hits, "evaluated_at": datetime.now().isoformat(timespec="seconds")}
    (week_dir / f"realized_summary{suffix}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[evaluate] {args.week} (values: {values_file.name})")
    print(res.round(4).to_string(index=False))
    print(f"[evaluate] MAE {mae:.4f} pp | RMSE {rmse:.4f} pp | direction {hits}/10 | total abs {out['total_abs_error']:.6f}")
    if missing:
        print(f"[evaluate] NOTE: {len(missing)} stock(s) missing target-Friday close, used last available: {missing}")


def main():
    ap = argparse.ArgumentParser(description="DASE7310 GP1 single-script pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("refresh-data"); p.add_argument("--end", default=None); p.set_defaults(func=cmd_refresh)
    p = sub.add_parser("backtest"); p.add_argument("--cutoff", required=True); p.set_defaults(func=cmd_backtest)
    p = sub.add_parser("snapshot"); p.add_argument("--cutoff", required=True); p.add_argument("--week", required=True)
    p.add_argument("--variant", default=None, help="可选：变体后缀（如 _qreg50），输出 predictions_variant.csv 等，不会覆盖既有快照")
    p.set_defaults(func=cmd_snapshot)
    p = sub.add_parser("evaluate"); p.add_argument("--week", required=True); p.add_argument("--values", default=None)
    p.add_argument("--suffix", default=None); p.set_defaults(func=cmd_evaluate)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
