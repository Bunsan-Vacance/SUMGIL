"""챔피언·챌린저 게이트 — 후보 모델을 챔피언과 비교해 채택/기각을 판정하는 순수 판정 모듈.

## 설계 근거

후보와 챔피언은 학습 구간이 달라 **각자의 lookup 기준선도 다르다.** 그래서 "후보의 lookup 대비
개선율"과 "챔피언의 lookup 대비 개선율"을 서로 빼면 기준이 다른 숫자끼리의 뺄셈이라 의미가 없다.
게이트는 두 모델의 예측 오차를 같은 실측 위에서 직접 비교한 **RMSE 상대차
`1 − RMSE_cand / RMSE_champ`(%p)** 를 쓴다. 날짜 단위 층화(요일유형) 부트스트랩으로 95% CI를 구한다.

채택 조건(타깃 boarding·alighting 모두 만족):

1. 점추정 ≥ `POINT_MIN_PP`(−0.5%p) — 챔피언보다 눈에 띄게 나빠지지 않는다.
2. CI 하한 ≥ `CI_LOWER_MIN_PP`(−2.0%p) — 나빠졌을 가능성이 큰 후보를 거른다.
3. 모든 가용성(`availability`)에서 후보가 **자기 lookup보다** 확실히 낫다(개선율 CI 하한 > 0).
4. sanity — 두 표의 행 수가 같고, 예측 NaN 비율이 1% 이하이며, (주어졌다면) 피처 열이 같다.

가용성이 있으면 가용성별로 따로 계산하고 전체 수치는 **행 전체를 한 번에 재표본한 값**(= 실제
행 비중으로 가중된 RMSE)을 쓴다. 가용성별 상대차의 행 비중 가중 평균은 참고용 `weighted_point`로
함께 남긴다(CI는 가중 평균으로 합칠 수 없어 합동 부트스트랩이 정석이다).

**첫 달은 판정만 기록한다(자동 승격 없음).** 이 모듈은 `gate.json`과 shadow 후보 등록까지만
하고 서빙 아티팩트를 바꾸지 않는다.

## 두 가지 모드

- `shadow`: 챔피언 판 채점(`score_daily`)과 shadow 판 채점을 **디렉터리 두 개**로 받는다.
  채점 행에는 챔피언/후보 구분 열이 없고(`predictor_version`은 메타 성격이며 보장되지 않는다),
  shadow 예측은 `data/CROWD/shadow/`에 따로 쌓여 채점도 따로 돌 수 있기 때문이다.
- `holdout`: 학습 직후 홀드아웃 구간을 두 아티팩트로 예측해 비교한다(`predictor.build_predictor`·
  `predict.predict_for_date` 재사용).

종료 코드: 0 채택, 3 기각, 2 입력 부족.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.retrain.common import (
    now_kst,
    read_json,
    write_json,
)
from app.CROWD.pipeline.retrain.drift import load_score_rows, scored_dates
from app.CROWD.pipeline.retrain.stats import (
    bootstrap_improvement,
    bootstrap_relative_rmse,
    daily_losses,
)

POINT_MIN_PP = -0.5
CI_LOWER_MIN_PP = -2.0
HOLDOUT_DAYS = 28
SHADOW_DAYS = 28
N_BOOT = 1000
MIN_DATES = 7
MAX_NAN_RATIO = 0.01

KEY = ["date", "station_no", "time_slot"]
TARGETS = ("boarding", "alighting")
ALL_GROUP = "all"

EXIT_ACCEPT = 0
EXIT_INSUFFICIENT = 2
EXIT_REJECT = 3


class GateInputError(ValueError):
    """게이트를 돌리기에 입력이 부족하다(공통 행 없음·날짜 부족 등). CLI 종료 코드 2."""


# ── 정렬·보조 ──
def _normalize(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    return out.drop_duplicates(KEY, keep="first").reset_index(drop=True)


def _day_type_strata(dates: pd.Series) -> pd.Series:
    """날짜별 요일유형 층(평일/토/일). 공휴일 파일 없이도 돌도록 요일만 본다. 인덱스 = 날짜."""
    uniq = pd.Series(pd.unique(dates)).sort_values()
    dow = uniq.dt.dayofweek.to_numpy()
    labels = np.where(dow < 5, "weekday", np.where(dow == 5, "sat", "sun"))
    return pd.Series(labels, index=pd.DatetimeIndex(uniq.to_numpy()))


def _align(
    rows_cand: pd.DataFrame, rows_champ: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """공통 키만 남겨 두 표를 같은 순서로 맞춘다."""
    cand_all, champ_all = _normalize(rows_cand), _normalize(rows_champ)
    cand_idx = cand_all.set_index(KEY)
    champ_idx = champ_all.set_index(KEY)
    common = cand_idx.index.intersection(champ_idx.index)
    info = {
        "n_cand_rows": len(cand_all),
        "n_champ_rows": len(champ_all),
        "n_common": len(common),
    }
    return cand_idx.loc[common].reset_index(), champ_idx.loc[common].reset_index(), info


def _nan_ratio(rows: pd.DataFrame) -> float:
    cols = [f"{t}_pred" for t in TARGETS]
    if rows.empty:
        return 1.0
    return float(rows[cols].isna().to_numpy().any(axis=1).mean())


def _stat(res: dict) -> dict:
    return {k: res[k] for k in ("point", "ci_low", "ci_high", "n_dates", "n_rows")}


def _empty_stat() -> dict:
    nan = float("nan")
    return {"point": nan, "ci_low": nan, "ci_high": nan, "n_dates": 0, "n_rows": 0}


def _relative(
    cand: pd.DataFrame, champ: pd.DataFrame, target: str, strata, n_boot: int, seed: int
) -> dict:
    """한 타깃의 직접 RMSE 상대차(%p). 후보·챔피언·실측이 모두 유한한 행만 쓴다."""
    cols = [f"{target}_actual", f"{target}_pred"]
    ok = cand[cols].notna().all(axis=1).to_numpy() & champ[cols].notna().all(axis=1).to_numpy()
    lc = daily_losses(cand[ok], f"{target}_pred", f"{target}_actual")
    lh = daily_losses(champ[ok], f"{target}_pred", f"{target}_actual")
    if len(lc) == 0:
        return _empty_stat()
    return _stat(bootstrap_relative_rmse(lc, lh, n_boot, seed, strata=strata))


def _versus_lookup(cand: pd.DataFrame, target: str, strata, n_boot: int, seed: int) -> dict:
    """후보의 자기 lookup 대비 개선율(기준 = lookup)."""
    cols = [f"{target}_actual", f"{target}_pred", f"{target}_lookup"]
    sub = cand[cand[cols].notna().all(axis=1)]
    model = daily_losses(sub, f"{target}_pred", f"{target}_actual")
    base = daily_losses(sub, f"{target}_lookup", f"{target}_actual")
    if len(model) == 0:
        return _empty_stat()
    return _stat(bootstrap_improvement(model, base, n_boot, seed, strata=strata))


# ── 핵심 판정 ──
def evaluate_gate(
    rows_cand: pd.DataFrame,
    rows_champ: pd.DataFrame,
    *,
    availability: str | None = None,
    use_availability: bool = True,
    n_boot: int = N_BOOT,
    seed: int = 0,
    feature_columns_cand: list[str] | None = None,
    feature_columns_champ: list[str] | None = None,
) -> dict:
    """후보·챔피언 행 단위 표(같은 키 `(date, station_no, time_slot)`)로 채택 여부를 판정한다.

    `availability`는 가용성 열 이름이다(None이면 `availability`). 열은 챔피언 표 것을 쓰고,
    없거나 `use_availability=False`면 전체만 계산한다. 공통 키가 없거나 날짜가 `MIN_DATES`개
    미만이면 `GateInputError`.
    """
    cand, champ, info = _align(rows_cand, rows_champ)
    if info["n_common"] == 0:
        raise GateInputError("후보·챔피언 공통 행이 없다")
    n_dates = int(cand["date"].nunique())
    if n_dates < MIN_DATES:
        raise GateInputError(f"공통 날짜 {n_dates}개 — {MIN_DATES}개 이상 필요")

    reasons: list[str] = []
    strata = _day_type_strata(cand["date"])

    # sanity
    sanity: dict = {
        "same_row_count": True,
        "nan_ratio_cand": _nan_ratio(cand),
        "nan_ratio_champ": _nan_ratio(champ),
    }
    if not (info["n_cand_rows"] == info["n_champ_rows"] == info["n_common"]):
        sanity["same_row_count"] = False
        reasons.append(
            f"sanity: 행 수 불일치(후보 {info['n_cand_rows']}, 챔피언 {info['n_champ_rows']}, "
            f"공통 {info['n_common']})"
        )
    for who, ratio in (("후보", sanity["nan_ratio_cand"]), ("챔피언", sanity["nan_ratio_champ"])):
        if ratio > MAX_NAN_RATIO:
            reasons.append(f"sanity: {who} 예측 NaN 비율 {ratio:.2%} > {MAX_NAN_RATIO:.0%}")
    if feature_columns_cand is not None and feature_columns_champ is not None:
        same = list(feature_columns_cand) == list(feature_columns_champ)
        sanity["same_feature_columns"] = same
        if not same:
            reasons.append("sanity: 후보·챔피언 피처 열이 다르다")

    # 가용성 그룹
    col = availability or "availability"
    groups: dict[str, np.ndarray] = {}
    if use_availability and col in champ.columns:
        labels = champ[col].fillna("unknown").astype(str).to_numpy()
        for label in sorted(set(labels)):
            groups[label] = labels == label
    else:
        groups[ALL_GROUP] = np.ones(len(cand), dtype=bool)

    by_availability: dict[str, dict] = {}
    for label, mask in groups.items():
        by_availability[label] = {
            "weight": float(mask.mean()),
            "n_rows": int(mask.sum()),
            "n_dates": int(cand.loc[mask, "date"].nunique()),
            "skipped": False,
            "targets": {},
        }

    targets: dict[str, dict] = {}
    for target in TARGETS:
        overall = _relative(cand, champ, target, strata, n_boot, seed)
        weighted = 0.0
        weight_sum = 0.0
        for label, mask in groups.items():
            slot = by_availability[label]
            if slot["n_dates"] < MIN_DATES:
                slot["skipped"] = True
                slot["skip_reason"] = f"날짜 {MIN_DATES}개 미만"
                continue
            c, h = cand[mask], champ[mask]
            rel = _relative(c, h, target, strata, n_boot, seed)
            slot["targets"][target] = {
                "vs_champion": rel,
                "vs_lookup": _versus_lookup(c, target, strata, n_boot, seed),
            }
            if np.isfinite(rel["point"]):
                weighted += slot["weight"] * rel["point"]
                weight_sum += slot["weight"]
        targets[target] = {
            "vs_champion": overall,
            "weighted_point": weighted / weight_sum if weight_sum > 0 else float("nan"),
        }

        point, low = overall["point"], overall["ci_low"]
        if not np.isfinite(point) or point < POINT_MIN_PP:
            reasons.append(f"{target}: 점추정 {point:+.2f}%p < {POINT_MIN_PP}%p")
        if not np.isfinite(low) or low < CI_LOWER_MIN_PP:
            reasons.append(f"{target}: CI 하한 {low:+.2f}%p < {CI_LOWER_MIN_PP}%p")
        for label, slot in by_availability.items():
            if slot["skipped"]:
                continue
            lk = slot["targets"][target]["vs_lookup"]
            if not np.isfinite(lk["ci_low"]) or lk["ci_low"] <= 0:
                reasons.append(
                    f"{target}: 가용성 {label} — lookup 대비 CI 하한 {lk['ci_low']:+.2f}% ≤ 0"
                )

    return {
        "accept": not reasons,
        "reasons": reasons,
        "targets": targets,
        "by_availability": by_availability,
        "sanity": sanity,
        "n_rows": int(info["n_common"]),
        "n_dates": n_dates,
        "params": {
            "point_min_pp": POINT_MIN_PP,
            "ci_lower_min_pp": CI_LOWER_MIN_PP,
            "n_boot": n_boot,
            "seed": seed,
            "strata": "day_type(weekday/sat/sun)",
            "availability_grouped": list(groups) != [ALL_GROUP],
        },
    }


# ── 모드 ──
def gate_shadow(
    champion_score_dir: Path,
    shadow_score_dir: Path,
    days: int = SHADOW_DAYS,
    *,
    n_boot: int = N_BOOT,
    seed: int = 0,
    feature_columns_cand: list[str] | None = None,
    feature_columns_champ: list[str] | None = None,
) -> dict:
    """두 `score_daily` 루트에서 양쪽에 모두 채점된 최근 `days`일을 읽어 판정한다."""
    champ_days = set(scored_dates(Path(champion_score_dir)))
    shadow_days = set(scored_dates(Path(shadow_score_dir)))
    common = sorted(champ_days & shadow_days)[-days:]
    if not common:
        raise GateInputError("챔피언·shadow 채점이 겹치는 날짜가 없다")
    start, end = common[0], common[-1]
    champ = load_score_rows(Path(champion_score_dir), start, end)
    cand = load_score_rows(Path(shadow_score_dir), start, end)
    if champ.empty or cand.empty:
        raise GateInputError("채점 행이 비어 있다")
    result = evaluate_gate(
        cand,
        champ,
        n_boot=n_boot,
        seed=seed,
        feature_columns_cand=feature_columns_cand,
        feature_columns_champ=feature_columns_champ,
    )
    result["mode"] = "shadow"
    result["window"] = [f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}"]
    return result


def _meta_features(artifact: Path) -> list[str] | None:
    meta = read_json(Path(artifact) / "meta.json")
    cols = (meta or {}).get("feature_columns")
    return list(cols) if cols else None


def _predict_holdout(
    artifact: Path, panel: pd.DataFrame, dates: list[pd.Timestamp]
) -> pd.DataFrame:
    # 무거운 의존성(lightgbm·torch)은 호출 시점에만 끌어온다.
    from app.CROWD.pipeline.predict import predict_for_date
    from app.CROWD.pipeline.predictor import artifact_kind, build_predictor

    predictor = build_predictor(artifact_kind(artifact), artifact_dir=Path(artifact))
    history = max(7, int(getattr(predictor, "required_history_days", 7)))
    pred = pd.concat(
        [predict_for_date(predictor, panel, d, history) for d in dates], ignore_index=True
    )
    actual = panel[[*KEY, *TARGETS]].rename(columns={t: f"{t}_actual" for t in TARGETS})
    return _normalize(pred).merge(_normalize(actual), on=KEY, how="inner")


def gate_holdout(
    panel_path: Path,
    champion_artifact: Path,
    candidate_artifact: Path,
    split_date: pd.Timestamp,
    days: int = HOLDOUT_DAYS,
    *,
    events_path: Path | None = None,
    n_boot: int = N_BOOT,
    seed: int = 0,
) -> dict:
    """학습 직후 홀드아웃(`split_date` 이후 `days`일)을 두 아티팩트로 예측해 판정한다.

    예측은 기존 공개 함수(`build_predictor`·`predict_for_date`)를 재사용한다. 가용성 정보가 없어
    전체만 계산한다. `events_path`는 후보를 학습시킨 이벤트 표(러너의 `auto/<run>/events.parquet`)를
    주기 위한 것이다 — 비우면 배포 이벤트 표(`EVENTS_NAME`)를 읽어 후보와 다른 표로 평가하게 된다.
    """
    from app.CROWD.pipeline.dataset import load_panel

    if events_path is None:
        panel = load_panel(with_events=True, panel_path=Path(panel_path))
    else:
        panel = load_panel(
            with_events=True, panel_path=Path(panel_path), events_path=Path(events_path)
        )
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    all_dates = sorted(d for d in panel["date"].unique() if d >= pd.Timestamp(split_date))
    dates = [pd.Timestamp(d) for d in all_dates[:days]]
    if not dates:
        raise GateInputError("split_date 이후 패널 날짜가 없다")
    cand = _predict_holdout(Path(candidate_artifact), panel, dates)
    champ = _predict_holdout(Path(champion_artifact), panel, dates)
    result = evaluate_gate(
        cand,
        champ,
        n_boot=n_boot,
        seed=seed,
        feature_columns_cand=_meta_features(candidate_artifact),
        feature_columns_champ=_meta_features(champion_artifact),
    )
    result["mode"] = "holdout"
    result["window"] = [f"{dates[0]:%Y-%m-%d}", f"{dates[-1]:%Y-%m-%d}"]
    return result


# ── 기록 ──
def write_gate_result(result: dict, out_path: Path) -> Path:
    """`gate.json`을 원자적으로 쓴다."""
    out_path = Path(out_path)
    write_json(out_path, {**result, "decided_at": now_kst().isoformat()})
    return out_path


def register_shadow_candidate(path: Path, artifact_name: str, gate_result: dict) -> bool:
    """게이트를 통과한 후보만 `shadow_candidates.json`에 추가한다. 추가했으면 True.

    기각이거나 이미 같은 이름이 있으면 False(중복 방지).
    """
    if not gate_result.get("accept"):
        return False
    path = Path(path)
    doc = read_json(path) or {}
    items = list(doc.get("candidates", []))
    if any(item.get("artifact") == artifact_name for item in items):
        return False
    items.append(
        {
            "artifact": artifact_name,
            "registered_at": now_kst().isoformat(),
            "mode": gate_result.get("mode"),
            "window": gate_result.get("window"),
            "point": {t: v["vs_champion"]["point"] for t, v in gate_result["targets"].items()},
        }
    )
    write_json(path, {"candidates": items})
    return True


# ── CLI ──
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="챔피언·챌린저 게이트")
    sub = ap.add_subparsers(dest="mode", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", required=True, help="gate.json 경로")
    common.add_argument("--n-boot", type=int, default=N_BOOT)
    common.add_argument("--seed", type=int, default=0)
    common.add_argument("--register", default=None, help="통과 시 shadow_candidates.json에 등록")
    common.add_argument("--artifact-name", default=None, help="--register 때 등록할 후보 이름")

    sh = sub.add_parser("shadow", parents=[common])
    sh.add_argument("--champion-score-dir", required=True)
    sh.add_argument("--shadow-score-dir", required=True)
    sh.add_argument("--days", type=int, default=SHADOW_DAYS)

    ho = sub.add_parser("holdout", parents=[common])
    ho.add_argument("--panel", required=True)
    ho.add_argument("--champion", required=True)
    ho.add_argument("--candidate", required=True)
    ho.add_argument("--split-date", required=True)
    ho.add_argument("--days", type=int, default=HOLDOUT_DAYS)
    ho.add_argument("--events", default=None, help="후보 학습에 쓴 이벤트 표(비우면 배포 표)")

    args = ap.parse_args(argv)
    try:
        if args.mode == "shadow":
            result = gate_shadow(
                Path(args.champion_score_dir),
                Path(args.shadow_score_dir),
                args.days,
                n_boot=args.n_boot,
                seed=args.seed,
            )
        else:
            result = gate_holdout(
                Path(args.panel),
                Path(args.champion),
                Path(args.candidate),
                pd.Timestamp(args.split_date),
                args.days,
                events_path=Path(args.events) if args.events else None,
                n_boot=args.n_boot,
                seed=args.seed,
            )
    except GateInputError as exc:
        print(f"[게이트] 입력 부족: {exc}", flush=True)
        sys.exit(EXIT_INSUFFICIENT)

    write_gate_result(result, Path(args.out))
    if args.register and args.artifact_name:
        added = register_shadow_candidate(Path(args.register), args.artifact_name, result)
        print(f"[게이트] shadow 후보 등록: {added}", flush=True)
    print(
        json.dumps({"accept": result["accept"], "reasons": result["reasons"]}, ensure_ascii=False)
    )
    sys.exit(EXIT_ACCEPT if result["accept"] else EXIT_REJECT)


if __name__ == "__main__":
    main(sys.argv[1:])
