"""예측 판 채점 — D일 예측을 D일 실측(D+1 수집)으로 채점해 `score_daily/dt=D/`에 남긴다.

## 채점 규칙

- **중복 제거 키 `(date, station_no, time_slot)`.** 예측 parquet은 (역, 방향, 30분 슬롯) 행이고
  `boarding_pred`·`alighting_pred`·`*_lookup`은 1시간 `time_slot` 값이 방향·30분 슬롯에 반복된다.
  그대로 채점하면 행이 방향×2배로 부풀어 가중이 틀어지므로 키로 중복을 제거한다.
- **`pred_source == "lookup_line9"` 행은 뺀다.** 9호선 2·3단계는 실측 원천에 없다.
- **누수 가드 3종**(셋 다 만족해야 채점 후보): `in_panel == False`(D가 학습 패널 안이면 이미
  본 날짜), `generated_at < D+1 00:00 KST`(D일이 끝난 뒤 만든 판은 실측을 봤을 수 있다),
  `predictor_override == False`(수동 지정 예측기는 운영 경로가 아니다). 탈락한 판은 사유를
  `excluded_candidates`로 메타에 남긴다.
- **판 선택.** 아카이브(`pred_archive/dt=D/gen=*/`) 전 판과 서빙 디렉터리 판 중 가드를 통과한
  것에서 `generated_at`이 가장 늦은 판을 쓴다.
- **공통 행만.** 예측과 실측을 키로 inner join한다. 예측에는 있으나 실측에 없는 역은
  `missing_stations`로 기록하고 **채우지 않는다**(검증 리포트 원칙 8: 표본 부족 구간에 값을
  채우지 않는다). 실측에만 있는 역은 `unpredicted_station_count`.
- **멱등 catch-up.** 이미 채점된 날짜는 `exists`로 건너뛴다(`--force`면 다시 채점). 기본은
  어제까지 N일을 훑어 빠진 날만 채운다.
- **종료 코드 99.** 새로 채점된 날이 없고 보류(`no_actuals`·`no_prediction`·`guard_excluded`)가
  하나라도 있으면 99 — 호출 측(DAG)이 "실측이 아직 안 왔다"를 재시도 신호로 쓴다.

TODO: 등급 일치율(L2)은 모니터링 전용 의사정답이라 구현을 미뤘다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.retrain.common import (
    KST,
    PRED_ARCHIVE_DIR,
    RECENT_LONG_PATH,
    SCORE_DIR,
    SCORE_META_NAME,
    SCORE_PARQUET_NAME,
    SERVING_DIR,
    atomic_write_parquet,
    load_deploy_stamp,
    now_kst,
    parse_generated_at,
    read_json,
    score_dir_for,
    today_kst,
    write_json,
)

KEY = ["date", "station_no", "time_slot"]
TARGETS = ("boarding", "alighting")
# batch_predict는 무거워 import하지 않고 값만 맞춘다.
LINE9_PRED_SOURCE = "lookup_line9"

PENDING_STATUSES = ("no_actuals", "no_prediction", "guard_excluded")


# ── 누수 가드·판 선택 ──
def leak_guard_reasons(meta: dict, target_date: pd.Timestamp) -> list[str]:
    """누수 가드 3종에 걸린 사유 목록. 비어 있으면 채점 후보다."""
    reasons: list[str] = []
    if meta.get("in_panel") is not False:
        reasons.append("in_panel")
    cutoff = (pd.Timestamp(target_date).normalize() + pd.Timedelta(days=1)).tz_localize(KST)
    generated = meta.get("generated_at")
    # 생성 시각을 알 수 없으면 D 이후에 만든 판일 수 있으므로 보수적으로 탈락시킨다.
    if not generated or parse_generated_at(str(generated)) >= cutoff:
        reasons.append("generated_after_cutoff")
    if meta.get("predictor_override") is not False:
        reasons.append("predictor_override")
    return reasons


def _meta_path(parquet_path: Path) -> Path:
    return parquet_path.with_suffix(".meta.json")


def find_prediction_candidates(
    target_date: pd.Timestamp, serving_dir: Path, archive_dir: Path
) -> list[Path]:
    """D일 예측 parquet 후보 — 아카이브 전 판(gen 정렬) 뒤에 서빙 판."""
    day = f"{pd.Timestamp(target_date):%Y-%m-%d}"
    name = f"predictions_{day}.parquet"
    found = sorted((Path(archive_dir) / f"dt={day}").glob(f"gen=*/{name}"))
    serving = Path(serving_dir) / name
    if serving.exists():
        found.append(serving)
    return found


def select_prediction(
    target_date: pd.Timestamp, serving_dir: Path, archive_dir: Path
) -> tuple[Path | None, dict | None, list[dict]]:
    """가드를 통과한 판 중 `generated_at`이 가장 늦은 것. `(path, meta, excluded)`."""
    excluded: list[dict] = []
    passed: list[tuple[pd.Timestamp, Path, dict]] = []
    for path in find_prediction_candidates(target_date, serving_dir, archive_dir):
        meta = read_json(_meta_path(path))
        if meta is None:
            excluded.append({"path": str(path), "generated_at": "", "reasons": ["meta_missing"]})
            continue
        reasons = leak_guard_reasons(meta, target_date)
        if reasons:
            excluded.append(
                {
                    "path": str(path),
                    "generated_at": str(meta.get("generated_at", "")),
                    "reasons": reasons,
                }
            )
            continue
        passed.append((parse_generated_at(str(meta["generated_at"])), path, meta))
    if not passed:
        return None, None, excluded
    _, path, meta = max(passed, key=lambda item: item[0])
    return path, meta, excluded


# ── 전처리 ──
def prepare_predictions(pred: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """9호선 lookup 행을 빼고 `(date, station_no, time_slot)` 키로 중복을 제거한다."""
    rows_raw = len(pred)
    kept = pred[pred["pred_source"] != LINE9_PRED_SOURCE]
    line9_dropped = rows_raw - len(kept)
    cols = [
        "date",
        "station_no",
        "line",
        "time_slot",
        "boarding_pred",
        "alighting_pred",
        "boarding_lookup",
        "alighting_lookup",
        "pred_source",
    ]
    out = kept[cols].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["station_no"] = out["station_no"].astype("int64")
    out = out.drop_duplicates(KEY, keep="first").reset_index(drop=True)
    stats = {
        "rows_raw": int(rows_raw),
        "rows_dedup": len(out),
        "line9_rows_dropped": int(line9_dropped),
    }
    return out, stats


def prepare_actuals(recent_long: pd.DataFrame, target_date: pd.Timestamp) -> pd.DataFrame:
    """롱 포맷 실측을 D일만 골라 (date, station_no, time_slot)당 한 행으로 피벗한다."""
    day = pd.Timestamp(target_date).normalize()
    cols = [*KEY, "boarding_actual", "alighting_actual"]
    df = recent_long.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df[(df["date"] == day) & df["direction"].isin(TARGETS)]
    if df.empty:
        return pd.DataFrame(columns=cols).astype({"station_no": "int64"})
    wide = (
        df.groupby([*KEY, "direction"])["passengers"]
        .sum(min_count=1)
        .unstack("direction")
        .reindex(columns=list(TARGETS))
        .rename(columns={t: f"{t}_actual" for t in TARGETS})
        .reset_index()
    )
    wide["station_no"] = wide["station_no"].astype("int64")
    return wide[cols]


# ── 지표 ──
def _target_metrics(frame: pd.DataFrame, target: str) -> dict:
    actual = frame[f"{target}_actual"].to_numpy(dtype="float64")
    model = frame[f"{target}_pred"].to_numpy(dtype="float64")
    base = frame[f"{target}_lookup"].to_numpy(dtype="float64")
    ok = np.isfinite(actual) & np.isfinite(model) & np.isfinite(base)
    out = {
        "n": int(ok.sum()),
        "rmse_model": float("nan"),
        "rmse_lookup": float("nan"),
        "mae_model": float("nan"),
        "mae_lookup": float("nan"),
        "improvement_rmse_pct": float("nan"),
        "improvement_mae_pct": float("nan"),
    }
    if not ok.any():
        return out
    err_m = model[ok] - actual[ok]
    err_b = base[ok] - actual[ok]
    out["rmse_model"] = float(np.sqrt(np.mean(err_m**2)))
    out["rmse_lookup"] = float(np.sqrt(np.mean(err_b**2)))
    out["mae_model"] = float(np.mean(np.abs(err_m)))
    out["mae_lookup"] = float(np.mean(np.abs(err_b)))
    if out["rmse_lookup"] > 0:
        out["improvement_rmse_pct"] = (1.0 - out["rmse_model"] / out["rmse_lookup"]) * 100.0
    if out["mae_lookup"] > 0:
        out["improvement_mae_pct"] = (1.0 - out["mae_model"] / out["mae_lookup"]) * 100.0
    return out


def metrics_for(frame: pd.DataFrame) -> dict:
    """타깃별(boarding·alighting) RMSE·MAE와 lookup 대비 개선율. NaN은 JSON 쓸 때 None."""
    return {target: _target_metrics(frame, target) for target in TARGETS}


# ── 채점 ──
def score_day(
    pred_prepared: pd.DataFrame, actuals: pd.DataFrame, meta: dict
) -> tuple[pd.DataFrame, dict]:
    """예측과 실측을 공통 행으로 inner join해 오차 열을 붙이고 요약을 만든다."""
    rows = pred_prepared.merge(actuals, on=KEY, how="inner")
    rows["availability"] = meta.get("availability")
    rows["predictor_version"] = meta.get("predictor_version")
    for target in TARGETS:
        rows[f"{target}_err"] = rows[f"{target}_pred"] - rows[f"{target}_actual"]
        rows[f"{target}_lookup_err"] = rows[f"{target}_lookup"] - rows[f"{target}_actual"]

    pred_stations = set(pred_prepared["station_no"].unique().tolist())
    actual_stations = set(actuals["station_no"].unique().tolist())
    missing = sorted(int(s) for s in pred_stations - actual_stations)
    by_line = {}
    for line, sub in rows.groupby("line", observed=True):
        by_line[str(line)] = {"n": len(sub), **metrics_for(sub)}
    summary = {
        "rows_scored": len(rows),
        "pred_rows": len(pred_prepared),
        "actual_rows": len(actuals),
        "missing_stations": missing,
        "missing_station_count": len(missing),
        "unpredicted_station_count": len(actual_stations - pred_stations),
        "metrics": metrics_for(rows),
        "by_line": by_line,
    }
    return rows, summary


def write_score(
    rows: pd.DataFrame, meta_out: dict, target_date: pd.Timestamp, out_root: Path
) -> Path:
    """`dt=D/part.parquet`와 `part.meta.json`을 원자적으로 쓰고 parquet 경로를 돌려준다."""
    out_dir = score_dir_for(target_date, out_root)
    parquet_path = out_dir / SCORE_PARQUET_NAME
    atomic_write_parquet(rows, parquet_path)
    write_json(out_dir / SCORE_META_NAME, meta_out)
    return parquet_path


def score_target_date(
    target_date: pd.Timestamp,
    *,
    serving_dir: Path = SERVING_DIR,
    archive_dir: Path = PRED_ARCHIVE_DIR,
    recent_long: pd.DataFrame | None,
    out_root: Path = SCORE_DIR,
    force: bool = False,
) -> dict:
    """한 날짜를 채점한다. status: scored / exists / no_prediction / no_actuals / guard_excluded."""
    day = pd.Timestamp(target_date).normalize()
    label = f"{day:%Y-%m-%d}"
    out_dir = score_dir_for(day, out_root)
    if not force and (out_dir / SCORE_META_NAME).exists():
        return {"date": label, "status": "exists", "path": str(out_dir / SCORE_PARQUET_NAME)}

    candidates = find_prediction_candidates(day, serving_dir, archive_dir)
    if not candidates:
        return {"date": label, "status": "no_prediction", "detail": "예측 판 없음"}
    pred_path, pred_meta, excluded = select_prediction(day, serving_dir, archive_dir)
    if pred_path is None or pred_meta is None:
        reasons = sorted({r for item in excluded for r in item["reasons"]})
        return {"date": label, "status": "guard_excluded", "detail": ",".join(reasons)}

    if recent_long is None:
        return {"date": label, "status": "no_actuals", "detail": "실측 파일 없음"}
    actuals = prepare_actuals(recent_long, day)
    if actuals.empty:
        return {"date": label, "status": "no_actuals", "detail": "해당 날짜 실측 없음"}

    pred_prepared, pred_stats = prepare_predictions(pd.read_parquet(pred_path))
    rows, summary = score_day(pred_prepared, actuals, pred_meta)
    meta_out = {
        "target_date": label,
        "scored_at": now_kst().isoformat(),
        "prediction_path": str(pred_path),
        "prediction_generated_at": pred_meta.get("generated_at"),
        "availability": pred_meta.get("availability"),
        "lag1d_available": pred_meta.get("lag1d_available"),
        "history_days_present": pred_meta.get("history_days_present"),
        "predictor": pred_meta.get("predictor"),
        "predictor_version": pred_meta.get("predictor_version"),
        "rows_scored": summary["rows_scored"],
        "pred_rows_raw": pred_stats["rows_raw"],
        "pred_rows_dedup": pred_stats["rows_dedup"],
        "line9_rows_dropped": pred_stats["line9_rows_dropped"],
        "actual_rows": summary["actual_rows"],
        "missing_station_count": summary["missing_station_count"],
        "missing_stations": summary["missing_stations"],
        "unpredicted_station_count": summary["unpredicted_station_count"],
        "metrics": summary["metrics"],
        "by_line": summary["by_line"],
        "excluded_candidates": excluded,
        "deploy_stamp": load_deploy_stamp(),
    }
    path = write_score(rows, meta_out, day, out_root)
    return {
        "date": label,
        "status": "scored",
        "path": str(path),
        "detail": f"{summary['rows_scored']}행",
    }


def run(
    dates: list[pd.Timestamp],
    *,
    serving_dir: Path = SERVING_DIR,
    archive_dir: Path = PRED_ARCHIVE_DIR,
    recent_long: pd.DataFrame | None = None,
    out_root: Path = SCORE_DIR,
    force: bool = False,
) -> list[dict]:
    return [
        score_target_date(
            d,
            serving_dir=serving_dir,
            archive_dir=archive_dir,
            recent_long=recent_long,
            out_root=out_root,
            force=force,
        )
        for d in dates
    ]


def exit_code(results: list[dict]) -> int:
    """새로 채점됐거나 전부 exists면 0, 새 채점 없이 보류가 있으면 99."""
    statuses = [r["status"] for r in results]
    if "scored" in statuses:
        return 0
    if any(s in PENDING_STATUSES for s in statuses):
        return 99
    return 0


def _load_recent_long(path: Path) -> pd.DataFrame | None:
    path = Path(path)
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="예측 판 채점(D일 예측 vs D일 실측)")
    ap.add_argument("--date", action="append", default=None, help="YYYY-MM-DD (반복 가능)")
    ap.add_argument("--catch-up-days", type=int, default=7, help="오늘−N ~ 어제를 훑는다")
    ap.add_argument("--serving-dir", default=str(SERVING_DIR))
    ap.add_argument("--archive-dir", default=str(PRED_ARCHIVE_DIR))
    ap.add_argument("--recent-long", default=str(RECENT_LONG_PATH))
    ap.add_argument("--out-dir", default=str(SCORE_DIR))
    ap.add_argument("--force", action="store_true", help="이미 채점된 날도 다시 채점")
    args = ap.parse_args(argv)

    if args.date:
        dates = [pd.Timestamp(d).normalize() for d in args.date]
    else:
        today = today_kst()
        dates = [today - pd.Timedelta(days=n) for n in range(args.catch_up_days, 0, -1)]

    results = run(
        dates,
        serving_dir=Path(args.serving_dir),
        archive_dir=Path(args.archive_dir),
        recent_long=_load_recent_long(Path(args.recent_long)),
        out_root=Path(args.out_dir),
        force=args.force,
    )
    for r in results:
        detail = f" ({r['detail']})" if r.get("detail") else ""
        print(f"[채점] {r['date']} → {r['status']}{detail}", flush=True)
    sys.exit(exit_code(results))


if __name__ == "__main__":
    main(sys.argv[1:])
