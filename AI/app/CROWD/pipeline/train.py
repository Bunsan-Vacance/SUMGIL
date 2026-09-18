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

## 결측 마스킹 학습(145)

143에서 배포 세트(LightGBM)는 시차가 전부 NaN이면 lookup보다 −37%였다 — 학습 때 그 상황을
한 번도 못 봤기 때문이다. `--mask-mode`로 켜면 `masking.assign_date_scenarios`가 **날짜
단위**로 시나리오(`full`/`d7_only`/`d1_only`/`no_lag`)를 뽑아 학습 프레임에 결측 상황을
섞는다(서빙은 하루 전체가 같은 시차 가용성을 공유하므로 행 단위가 아니라 날짜 단위로 뽑는다).
`stack`(기본)은 원본에 마스킹 사본을 이어붙이고, `replace`는 마스킹된 사본으로 통째로 바꾼다.

마스킹 실험 아티팩트는 `--out-root`로 `models/CROWD/_experiments/…` 아래에 저장한다 —
`predictor.latest_artifact`는 `models/CROWD/` 바로 아래 폴더를 이름 정렬로 골라 `auto`
기본값을 정하므로, 마스킹 실험 폴더가 그 자리에 섞이면 이름 운으로 프로덕션 기본값이
실험 아티팩트로 바뀔 수 있다.

## 연도 표본 가중 학습(227)

lookup(요일유형×역×시간대 평균)과 잔차 LightGBM은 연도·추세 항이 없어, 학습 창을 2022~로
넓히면 옛 연도로 끌린 평균이 된다. `--year-weights`(예: `"2022:0.25,2023:0.5,2024:1.0"`)로
연도별 표본 가중을 lookup 가중 평균과 LightGBM `sample_weight` 양쪽에 **같은 값**으로 준다.
파생 캐시(시차 잔차)는 lookup 값에 의존하므로 가중 lookup으로 만든 파생은 평탄 lookup 파생과
다르다 — `--derived-cache`를 따로 지정해야 한다(`--panel` 가드와 같은 자리에 있다).

실행:
    cd AI
    python -m app.CROWD.pipeline.train --feature-set festival_all_derived_resid
    python -m app.CROWD.pipeline.train --feature-set festival_all_derived_resid --group-col line
    python -m app.CROWD.pipeline.train --mask-mode stack
        --out-root models/CROWD/_experiments/masking --name w2024_masked-stack   # (한 줄로)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    CROWD_PROCESSED,
    DERIVED_CACHE,
    EVENTS_NAME,
    PANEL_NAME,
    SPLIT_DATE,
    load_or_build_derived,
    load_panel,
    time_split,
)
from app.CROWD.pipeline.features import (
    CATEGORICAL_COLS,
    DERIVED_VERSION,
    FEATURE_SETS,
    build_matrix,
)
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.masking import assign_date_scenarios, count_dates_by_scenario, mask_by_date

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


@dataclass(frozen=True)
class MaskingSpec:
    """결측 마스킹 학습 설정(145). `weights`는 `masking.assign_date_scenarios`로 그대로 넘어가는
    시나리오별 확률(날짜 단위)이라 키·합계 검증은 거기서 한다 — 여기서는 `mode`만 검증한다."""

    mode: str  # "stack" | "replace"
    weights: dict[str, float]
    seed: int = 42

    def __post_init__(self) -> None:
        if self.mode not in ("stack", "replace"):
            raise ValueError(f"mode는 'stack' 또는 'replace'만 지원한다 — {self.mode!r}")
        if self.mode == "stack" and "full" in self.weights:
            raise ValueError(
                "stack 모드에서는 원본 행 자체가 이미 'full' 몫이다 — weights에 'full'을 "
                "또 넣으면 그 비중이 이중으로 반영된다."
            )


# 145 실험 기본값. stack: 원본(=full)에 결측 시나리오 사본을 이어붙인다.
STACK_WEIGHTS = {"d7_only": 0.5, "no_lag": 0.3, "d1_only": 0.2}
# replace: 원본을 통째로 마스킹된 사본으로 바꾸므로 full도 하나의 시나리오로 포함한다.
REPLACE_WEIGHTS = {"full": 0.5, "d7_only": 0.25, "no_lag": 0.15, "d1_only": 0.10}


# ── 연도 표본 가중(227) ──


def parse_year_weights(text: str | None) -> dict[int, float] | None:
    """`--year-weights` CLI 값 파싱. `"2022:0.25,2023:0.5"` → `{2022: 0.25, 2023: 0.5}`.

    `None`이거나 빈 문자열이면 `None`(가중 없음). 형식 오류·가중치 0 이하·연도 중복은
    CLI 입력 검증이라 `SystemExit`로 바로 멈춘다(무엇이 잘못됐는지 한국어로 알린다).
    """
    if not text or not text.strip():
        return None
    weights: dict[int, float] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        year_str, sep, weight_str = part.partition(":")
        if not sep:
            raise SystemExit(
                f"--year-weights 형식이 잘못됐다(예: '2022:0.25,2023:0.5') — "
                f"콜론(:)이 없다: {part!r}"
            )
        try:
            year = int(year_str.strip())
        except ValueError as exc:
            raise SystemExit(f"--year-weights의 연도를 정수로 읽을 수 없다: {year_str!r}") from exc
        try:
            weight = float(weight_str.strip())
        except ValueError as exc:
            raise SystemExit(
                f"--year-weights의 가중치를 숫자로 읽을 수 없다: {weight_str!r}"
            ) from exc
        if weight <= 0:
            raise SystemExit(f"--year-weights의 가중치는 0보다 커야 한다 — {year}:{weight}")
        if year in weights:
            raise SystemExit(f"--year-weights에 연도 {year}가 중복됐다")
        weights[year] = weight
    return weights or None


def year_weights_label(year_weights: dict[int, float] | None) -> str:
    """캐시 메타·아티팩트 meta에 쓰는 정규형 — 연도 오름차순 `"2022:0.25,2023:0.5"`. 없으면 `"none"`."""
    if not year_weights:
        return "none"
    return ",".join(f"{year}:{year_weights[year]}" for year in sorted(year_weights))


def year_weight_series(dates: pd.Series, year_weights: dict[int, float] | None) -> pd.Series:
    """날짜별 연도 가중 — `year_weights`에 없는 연도는 1.0. `dates.index`를 그대로 유지한다."""
    years = pd.to_datetime(dates).dt.year
    if not year_weights:
        return pd.Series(1.0, index=dates.index, dtype="float64")
    return years.map(lambda y: float(year_weights.get(int(y), 1.0))).astype("float64")


def apply_masking(
    train: pd.DataFrame, feature_cols: Sequence[str], spec: MaskingSpec
) -> tuple[pd.DataFrame, dict]:
    """`spec`대로 결측 시나리오를 섞은 학습 프레임과 요약을 돌려준다.

    **왜 날짜 단위인가** — 서빙에서는 하루 전체가 같은 시차 가용성 상태를 공유한다(전날
    배치가 안 왔으면 그날 모든 역·슬롯이 같이 없다). 행 단위로 섞으면 모델이 서빙에서
    실제로 겪지 않는 "같은 날 안에서 시차가 있다/없다가 섞인" 조합을 학습하게 된다.
    **왜 stack이 기본인가** — `replace`는 원본(`full`) 행을 통째로 마스킹된 사본으로
    바꿔버려 "이력이 온전한 날"의 학습 비중이 줄어든다. `stack`은 원본을 그대로 두고
    마스킹 사본을 이어붙이므로 `full` 레짐을 약화하지 않으면서 결측 시나리오를 더 보여준다.
    """
    rng = np.random.default_rng(spec.seed)
    date_scenarios = assign_date_scenarios(train["date"], spec.weights, rng)
    masked = mask_by_date(train, date_scenarios, feature_cols)

    if spec.mode == "stack":
        out = pd.concat([train, masked], ignore_index=True)
    else:
        out = masked.reset_index(drop=True)

    summary = {
        "mode": spec.mode,
        "weights": dict(spec.weights),
        "seed": spec.seed,
        "date_level": True,
        "n_dates": len(date_scenarios),
        "n_dates_by_scenario": count_dates_by_scenario(date_scenarios),
        "n_rows_in": len(train),
        "n_rows_out": len(out),
    }
    return out, summary


def _augment(
    train: pd.DataFrame, feature_set: str, masking: MaskingSpec | None
) -> tuple[pd.DataFrame, dict | None]:
    """`masking`이 없으면 원본 그대로(요약 None), 있으면 `apply_masking` 결과를 돌려준다."""
    if masking is None:
        return train, None
    return apply_masking(train, FEATURE_SETS[feature_set], masking)


def _fit_lgbm(
    X: pd.DataFrame,
    y: pd.Series,
    params: dict,
    sample_weight: np.ndarray | pd.Series | None = None,
):
    from lightgbm import LGBMRegressor

    model = LGBMRegressor(**params)
    model.fit(X, y, sample_weight=sample_weight)  # None이면 지금과 동일(lightgbm이 허용)
    return model


def _group_key(value) -> str:
    return "__all__" if value is None else str(value)


def train_models(
    train: pd.DataFrame,
    lookup: DayTypeLookupBaseline,
    feature_set: str,
    params: dict | None = None,
    group_col: str | None = None,
    masking: MaskingSpec | None = None,
    year_weights: dict[int, float] | None = None,
) -> dict[str, dict[str, object]]:
    """잔차 모델을 타깃별(·그룹별)로 fit한다. 반환: {target: {group_key: booster}}.

    `masking`을 주면 `apply_masking`으로 증강한 프레임에 대해 잔차·피처·그룹 마스크를
    다시 계산한 뒤 fit한다(잔차는 승하차·lookup 키에만 의존해 증강된 프레임에도 그대로
    유효하고, 그룹 마스크도 증강 후 행 수에 맞춰 다시 만들어야 한다). `masking=None`이면
    오늘과 동일하게 동작한다.

    `year_weights`(227)는 `_augment` **뒤**의 `train["date"]`로 가중을 계산한다 — stack
    증강의 마스킹 사본도 원본과 같은 날짜를 그대로 가지므로 자연히 같은 연도 가중을 받는다.
    `year_weights=None`이면 `sample_weight=None`으로 지금과 동일하게 fit한다.
    """
    params = {**DEFAULT_PARAMS, **(params or {})}
    train, _ = _augment(train, feature_set, masking)
    resid = lookup.residuals(train)
    X = build_matrix(train, feature_set)
    weights = year_weight_series(train["date"], year_weights).to_numpy() if year_weights else None
    groups = [None] if group_col is None else sorted(train[group_col].dropna().unique())

    models: dict[str, dict[str, object]] = {}
    for target in TARGETS:
        y = resid[f"{target}_resid"]
        models[target] = {}
        for g in groups:
            mask = (
                np.ones(len(train), dtype=bool) if g is None else (train[group_col] == g).to_numpy()
            )
            sw = weights[mask] if weights is not None else None
            models[target][_group_key(g)] = _fit_lgbm(X[mask], y[mask], params, sample_weight=sw)
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
    masking: MaskingSpec | None = None,
    panel_path: Path | None = None,
    events_path: Path | None = None,
    derived_cache: Path | None = None,
    name: str | None = None,
    year_weights: dict[int, float] | None = None,
) -> Path:
    """패널 로딩 → lookup fit → 파생 → (선택) 마스킹 증강 → 잔차 모델 fit → 아티팩트 저장.

    디렉터리 경로를 돌려준다.
    """
    if panel_path is not None and derived_cache is None:
        raise SystemExit(
            "--panel을 바꾸면 --derived-cache도 따로 줘야 한다 — 기본 캐시"
            "(crowd_panel_derived_2024_2025)를 덮어쓴다"
        )
    if masking is not None and Path(out_root).resolve() == MODELS_DIR.resolve():
        raise SystemExit(
            "마스킹 실험 아티팩트는 models/CROWD/ 바로 아래에 두지 않는다 — "
            "predictor.latest_artifact가 이름 정렬로 auto 기본값을 고르므로 프로덕션이 바뀔 수 있다. "
            "--out-root models/CROWD/_experiments/<실험명> 을 준다(채택 시에만 승격)"
        )
    if year_weights is not None and derived_cache is None:
        raise SystemExit(
            "--year-weights는 --derived-cache를 따로 줘야 한다 — 가중 lookup으로 기본 캐시"
            "(crowd_panel_derived_2024_2025)를 덮어쓴다"
        )

    resolved_panel = panel_path or (CROWD_PROCESSED / PANEL_NAME)
    resolved_events = events_path or (CROWD_PROCESSED / EVENTS_NAME)
    resolved_cache = derived_cache or DERIVED_CACHE

    load_kwargs: dict[str, Path] = {}
    if panel_path is not None:
        load_kwargs["panel_path"] = panel_path
    if events_path is not None:
        load_kwargs["events_path"] = events_path
    panel = load_panel(with_events=True, **load_kwargs)
    train_raw, _ = time_split(panel, split_date)
    lookup_weights = year_weight_series(train_raw["date"], year_weights) if year_weights else None
    lookup = DayTypeLookupBaseline().fit(train_raw, weights=lookup_weights)
    derived = load_or_build_derived(
        panel,
        lookup,
        cache_path=resolved_cache,
        panel_path=resolved_panel,
        lookup_weights=year_weights_label(year_weights),
        events_path=resolved_events,
    )
    train, _ = time_split(derived, split_date)

    # 여기서 한 번만 증강해 n_train_rows·아티팩트가 실제 학습 행 수(stack이면 2배)를
    # 반영하게 하고, train_models에는 이미 증강된 프레임을 masking=None으로 넘겨
    # 이중 증강을 막는다.
    train, mask_summary = _augment(train, feature_set, masking)
    models = train_models(train, lookup, feature_set, params, group_col, year_weights=year_weights)

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
        "training": {
            "masking": mask_summary,
            "year_weights": year_weights_label(year_weights) if year_weights else None,
            "panel_file": Path(resolved_panel).name,
            "events_file": Path(resolved_events).name,
            "derived_cache": Path(resolved_cache).name,
        },
    }
    out_dir = Path(out_root) / (name if name else f"{feature_set}_{stamp}")
    if out_dir.exists():
        raise SystemExit(f"아티팩트 폴더가 이미 있다 — 덮어쓰지 않는다: {out_dir}")
    out_dir = save_artifact(out_dir, lookup, models, meta)
    print(f"[학습] 저장: {out_dir} (학습 {len(train):,}행, 그룹 {group_col or '없음'})", flush=True)
    return out_dir


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # 기본은 D-1 배포 세트. 전부 세트는 실시간 승하차 원천이 확보됐을 때 따로 학습한다 —
    # 전부 세트로 학습하고 실시간 컬럼을 NaN으로 서빙하면 +4~8%에 그친다(evaluate_final 1절).
    ap.add_argument(
        "--feature-set", default="festival_selflag_d1sd_d7_resid", choices=sorted(FEATURE_SETS)
    )
    ap.add_argument("--group-col", default=None, help="예: line — 그룹별로 잔차 모델을 따로 fit")
    ap.add_argument("--params", default=None, help="JSON, 예: '{\"num_leaves\": 127}'")
    ap.add_argument(
        "--mask-mode",
        default="none",
        choices=["none", "stack", "replace"],
        help="145 결측 마스킹 학습(none이면 기존과 동일)",
    )
    ap.add_argument(
        "--mask-weights",
        default=None,
        help='JSON, 예: \'{"d7_only": 0.5, "no_lag": 0.3, "d1_only": 0.2}\' (기본: mode별 프리셋)',
    )
    ap.add_argument("--mask-seed", type=int, default=42)
    ap.add_argument(
        "--panel", default=None, help=f"패널 파일명 — 상대경로면 {CROWD_PROCESSED} 기준"
    )
    ap.add_argument(
        "--events", default=None, help=f"이벤트 파일명 — 상대경로면 {CROWD_PROCESSED} 기준"
    )
    ap.add_argument(
        "--derived-cache", default=None, help=f"파생 캐시 파일명 — 상대경로면 {CROWD_INTERIM} 기준"
    )
    ap.add_argument("--split-date", default=str(SPLIT_DATE.date()), help="YYYY-MM-DD")
    ap.add_argument("--out-root", default=str(MODELS_DIR))
    ap.add_argument("--name", default=None, help="아티팩트 폴더명 — 주면 스탬프 없이 그대로 쓴다")
    ap.add_argument(
        "--year-weights",
        default=None,
        help=(
            "227 연도별 표본 가중, 예: '2022:0.25,2023:0.5,2024:1.0'(기본 없음 — 전부 1.0). "
            "lookup 가중 평균과 LightGBM sample_weight 양쪽에 같은 값을 준다. "
            "--derived-cache를 반드시 같이 줘야 한다(기본 캐시는 평탄 lookup 전제)"
        ),
    )
    args = ap.parse_args(argv)

    masking = None
    if args.mask_mode != "none":
        default_weights = STACK_WEIGHTS if args.mask_mode == "stack" else REPLACE_WEIGHTS
        weights = json.loads(args.mask_weights) if args.mask_weights else default_weights
        masking = MaskingSpec(mode=args.mask_mode, weights=weights, seed=args.mask_seed)
    year_weights = parse_year_weights(args.year_weights)

    def _resolve(value: str | None, base: Path) -> Path | None:
        if value is None:
            return None
        p = Path(value)
        return p if p.is_absolute() else base / p

    run(
        args.feature_set,
        args.group_col,
        json.loads(args.params) if args.params else None,
        split_date=pd.Timestamp(args.split_date),
        out_root=Path(args.out_root),
        masking=masking,
        panel_path=_resolve(args.panel, CROWD_PROCESSED),
        events_path=_resolve(args.events, CROWD_PROCESSED),
        derived_cache=_resolve(args.derived_cache, CROWD_INTERIM),
        name=args.name,
        year_weights=year_weights,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
