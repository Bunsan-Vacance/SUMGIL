"""잔차 모델 학습 → 아티팩트 저장.

    최종 예측 = lookup(요일유형×역×시간대 평균) + 잔차 모델(LightGBM)

두 단계를 하나의 아티팩트 디렉터리로 묶어 저장한다. `predict.py`가 같은 디렉터리를 읽어
같은 파생 함수(`features.add_derived_columns`)로 피처를 만들고 재구성한다.

    models/CROWD/<feature_set>_<YYYYMMDD-HHMM>/
      lookup.parquet          lookup 테이블
      model_boarding.txt      LightGBM booster (타깃별)
      model_alighting.txt
      meta.json               세트·컬럼·파생 버전·학습 구간·하이퍼파라미터·학습 지표

**그룹별 학습(`group_col`).** 93번(호선·군집별 분할 검토)이 "파생은 전역, fit만 그룹별"로
비교할 수 있게 처음부터 인자로 받는다. 지정하면 그룹 값마다 잔차 모델을 따로 fit해
`model_<target>__<group>.txt`로 저장하고, predict는 행의 그룹 값으로 모델을 고른다.
lookup은 그룹과 무관하게 전역 하나다(키에 station_no가 이미 있다).

무거운 의존성(lightgbm)은 함수 안에서 지연 import한다(`AI/CLAUDE.md`).

실행:
    cd AI
    python -m app.CROWD.pipeline.train --feature-set festival_all_derived_resid
    python -m app.CROWD.pipeline.train --feature-set festival_all_derived_resid --group-col line
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.dataset import SPLIT_DATE, load_or_build_derived, load_panel, time_split
from app.CROWD.pipeline.features import (
    CATEGORICAL_COLS,
    DERIVED_VERSION,
    FEATURE_SETS,
    build_matrix,
)
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline

AI_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = AI_ROOT / "models" / "CROWD"

# 90 그리드(num_leaves 31/63/127 × n_estimators 300/600, 시차 전용 세트, 2024/2025 분할)에서
# 승차·하차 평균 RMSE 개선율 최고(23.05%)였던 조합. 차이는 1%p 안이라 더 작은 모델을 택했다.
# 600그루는 전 조합에서 300그루보다 나빠 과적합 쪽이다(`evaluate_final.py` 3절).
DEFAULT_PARAMS = {
    "n_estimators": 300,
    "num_leaves": 31,
    "learning_rate": 0.05,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}


def _fit_lgbm(X: pd.DataFrame, y: pd.Series, params: dict):
    from lightgbm import LGBMRegressor

    model = LGBMRegressor(**params)
    model.fit(X, y)
    return model


def _group_key(value) -> str:
    return "__all__" if value is None else str(value)


def train_models(
    train: pd.DataFrame,
    lookup: DayTypeLookupBaseline,
    feature_set: str,
    params: dict | None = None,
    group_col: str | None = None,
) -> dict[str, dict[str, object]]:
    """잔차 모델을 타깃별(·그룹별)로 fit한다. 반환: {target: {group_key: booster}}."""
    params = {**DEFAULT_PARAMS, **(params or {})}
    resid = lookup.residuals(train)
    X = build_matrix(train, feature_set)
    groups = [None] if group_col is None else sorted(train[group_col].dropna().unique())

    models: dict[str, dict[str, object]] = {}
    for target in TARGETS:
        y = resid[f"{target}_resid"]
        models[target] = {}
        for g in groups:
            mask = (
                np.ones(len(train), dtype=bool) if g is None else (train[group_col] == g).to_numpy()
            )
            models[target][_group_key(g)] = _fit_lgbm(X[mask], y[mask], params)
    return models


def save_artifact(
    out_dir: Path,
    lookup: DayTypeLookupBaseline,
    models: dict[str, dict[str, object]],
    meta: dict,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lookup.save(out_dir / "lookup.parquet")
    files: dict[str, dict[str, str]] = {}
    for target, by_group in models.items():
        files[target] = {}
        for gkey, booster in by_group.items():
            suffix = "" if gkey == "__all__" else f"__{gkey}"
            name = f"model_{target}{suffix}.txt"
            booster.booster_.save_model(str(out_dir / name))
            files[target][gkey] = name
    (out_dir / "meta.json").write_text(
        json.dumps({**meta, "model_files": files}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return out_dir


def run(
    feature_set: str,
    group_col: str | None = None,
    params: dict | None = None,
    split_date: pd.Timestamp = SPLIT_DATE,
    out_root: Path = MODELS_DIR,
) -> Path:
    """패널 로딩 → lookup fit → 파생 → 잔차 모델 fit → 아티팩트 저장. 디렉터리 경로를 돌려준다."""
    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel, split_date)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_or_build_derived(panel, lookup)
    train, _ = time_split(derived, split_date)

    models = train_models(train, lookup, feature_set, params, group_col)

    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M")
    meta = {
        "feature_set": feature_set,
        "feature_columns": FEATURE_SETS[feature_set],
        "categorical_columns": [c for c in CATEGORICAL_COLS if c in FEATURE_SETS[feature_set]],
        "targets": TARGETS,
        "lookup_keys": lookup.keys,
        "group_col": group_col,
        "derived_version": DERIVED_VERSION,
        "train_start": str(train["date"].min().date()),
        "train_end": str(train["date"].max().date()),
        "split_date": str(pd.Timestamp(split_date).date()),
        "n_train_rows": len(train),
        "params": {**DEFAULT_PARAMS, **(params or {})},
        "created_at": stamp,
    }
    out_dir = save_artifact(out_root / f"{feature_set}_{stamp}", lookup, models, meta)
    print(f"[학습] 저장: {out_dir} (학습 {len(train):,}행, 그룹 {group_col or '없음'})", flush=True)
    return out_dir


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # 기본은 D-1 배포 세트. 전부 세트는 실시간 승하차 원천이 확보됐을 때 따로 학습한다 —
    # 전부 세트로 학습하고 실시간 컬럼을 NaN으로 서빙하면 +4~8%에 그친다(evaluate_final 1절).
    ap.add_argument(
        "--feature-set", default="festival_selflag_d1d7_resid", choices=sorted(FEATURE_SETS)
    )
    ap.add_argument("--group-col", default=None, help="예: line — 그룹별로 잔차 모델을 따로 fit")
    ap.add_argument("--params", default=None, help="JSON, 예: '{\"num_leaves\": 127}'")
    args = ap.parse_args(argv)
    run(args.feature_set, args.group_col, json.loads(args.params) if args.params else None)


if __name__ == "__main__":
    main(sys.argv[1:])
