"""배치 추론 잡 — 대상 날짜의 전 역·전 시간대 혼잡도 표를 만들어 서빙 디렉터리에 저장한다.

    패널(최근 이력 창 + 대상 날짜 골격)                              창 길이 = 예측기의 required_history_days
      → Predictor.predict (lookup / lightgbm / dl / llm 중 설정값)   승하차 예측
      → recursive_congestion (재귀식 방향 분해)                      1시간 재차인원
      → apply_calibration (배율표)                                  30분 보정 혼잡도
      → grade (임계치)                                              등급
      → data/CROWD/serving/predictions_YYYY-MM-DD.parquet + .meta.json

API는 요청 시점에 모델을 돌리지 않고 이 표만 읽는다(`AI/CLAUDE.md`: 서빙 경로는 가벼운 의존성만).
하루치는 273역 × 20슬롯 × 2방향 × 2(30분) ≈ 21,840행, 재귀식 포함 1분 안쪽.

## 대상 날짜가 패널에 있는가 없는가

- **패널에 있는 날짜**(과거 재현·검증용): 그 날 행을 그대로 창에 넣고 예측한다. 실측이 있으니
  `actual_*` 컬럼도 같이 남겨 API가 "예측 vs 실측"을 보여줄 수 있다.
- **패널에 없는 날짜**(오늘·내일 — 실제 운영): 역 × 20슬롯 골격을 만들고 달력에서 day_type, 이벤트
  테이블에서 경기·축제(없으면 0), 승하차는 NaN으로 둔다. 시차 피처는 창에 든 과거 행에서 채워진다.
  패널(연간 CSV, 2025-12까지) 뒤에는 D−1 수집기(`DATA_ENGINE/collect/subway_ridership_daily.py`)가 쌓은
  `data/CROWD/interim/crowd_recent_ridership_long.parquet`을 이어 붙여 이력 창을 채운다(143). 내일은 `lag1d`
  (전날)가 비어 `lag7d`만으로 예측되는데 이 사실을 `lag1d_available`로 표시한다.

## 가용성별 예측기 라우팅(197) — `routing.py`

이력 완비(`full`)/결손(`d1_only`·`d7_only`)/전무(`no_lag`)에 따라 쓰는 예측기가 다르다(145
`family-check/RESULTS.md` 8절 판정). `predict_day`가 `routing.availability()` → `routing.select()`로
그날의 kind를 정하고, `run()`이 필요한 예측기만 지연 로드해 같은 kind는 재사용한다. **`no_lag`도
LightGBM 대신 lookup으로 조용히 넘어가던 옛 fallback은 없어졌다** — 지금은 `no_lag`도 라우팅이
정한 예측기(GRU)를 쓰고, 그 사실이 meta의 `availability`·`routing_rule`에 남는다. `--predictor` CLI로
kind를 명시하면 라우팅을 건너뛰고 그 kind 하나로 전 날짜를 예측한다(디버그·재현용) — 이때
`routing_rule`은 `null`, `predictor_override`는 `true`다.

## 결측은 상태로 노출한다

lookup 조회 실패(학습 구간에 없는 요일유형×역×시간대)와 배율표 결측(2호선 지선 방향 체계, 결번 역)은
값을 채우지 않고 `data_status`로 남긴다. API가 이 셀을 "데이터 부족"으로 표시한다(원칙 8). 예측 승하차
음수는 그 타깃의 lookup 값으로 대체하고(197 B-2), lookup도 없거나 음수면 0으로 둔다(`pred_source`로
노출). 상태 값은 우선순위 순으로 다음 다섯이다(146에서 둘 추가):

    no_lookup            기준선(lookup) 자체가 없음 — 혼잡도 이전 단계에서 끊김
    ok                   예측·배율 모두 정상
    calibration_fallback 1~8호선 공휴일이라 일요일 배율을 빌려 씀(값은 있다, 대체 사실을 밝히는 것)
    segment_truncated    절단 구간의 종점 링크 — 구조적으로 재차 0이라 배율이 없는 셀(199에서 1호선 전용
                         `line1_truncated`를 전 절단 구간으로 넓혔다. 경계 유입을 반영한 배율표에서는
                         대부분 `ok`가 되고, 상수를 못 구한 셀만 여기 남는다)
    no_calibration       그 밖의 배율표 결측(결번 역, 대응 못 한 2호선 지선)

실행:
    cd AI
    python -m app.CROWD.pipeline.batch_predict --date 2025-06-02            # 패널 안 날짜(재현)
    python -m app.CROWD.pipeline.batch_predict --date 2026-01-05 --predictor lookup
    python -m app.CROWD.pipeline.batch_predict --today --tomorrow             # 운영
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.CROWD.pipeline import routing
from app.CROWD.pipeline.calendar import attach_calendar, holiday_coverage_end, load_holidays
from app.CROWD.pipeline.congestion import (
    HOLIDAY_FALLBACK_DAY_TYPE,
    apply_calibration,
    grade,
    recursive_congestion,
    truncated_boundary_cells,
)
from app.CROWD.pipeline.dataset import (
    CROWD_PROCESSED,
    EVENT_COUNT_COLS,
    EVENTS_NAME,
    extend_panel_with_recent,
    load_panel,
    load_recent_long,
    resolved_segments,
)
from app.CROWD.pipeline.features import SLOT_ORDER
from app.CROWD.pipeline.lookup import TARGETS
from app.CROWD.pipeline.predictor import (
    Predictor,
    artifact_kind,
    build_predictor,
    latest_artifact,
)
from app.CROWD.pipeline.topology import load_capacity

CALIBRATION_NAME = "crowd_congestion_calibration.parquet"
HISTORY_DAYS = 7
EVENT_NUMERIC_COLS = ["game_attendance", "game_attendance_missing", "festival_min_duration_days"]

# 아래 세 상수는 `SERVING_CONTRACT.md`(출력 계약)와 짝을 이룬다. 하나를 고치면 문서도 같이 고쳐야
# 하고, 어긋나면 `test/CROWD/test_crowd_serving_contract.py`가 막는다 — 문서를 사람 기억이 아니라
# 테스트로 붙들어 두려는 장치다(197 C부).

# 표에 실리는 `data_status` 값. 우선순위는 `to_congestion_table` 참고.
DATA_STATUS_VALUES = (
    "ok",
    "calibration_fallback",
    "segment_truncated",
    "no_calibration",
    "no_lookup",
)
# 표에는 없고 API에서만 나타나는 상태(그 날짜 표가 아직 없음 -> 404).
API_ONLY_DATA_STATUS = ("no_data",)

# `.meta.json`에 실리는 키와 그 순서. `predict_day`가 만드는 앞쪽 13개 + `run`이 덧붙이는 8개.
META_KEYS = (
    "target_date",
    "in_panel",
    "history_window_days",
    "history_days_present",
    "history_dates",
    "lag1d_available",
    "lag7d_available",
    "availability",
    "routing_rule",
    "predictor",
    "predictor_version",
    "predictor_override",
    "predictor_fallback",
    "recent_dates_available",
    "grade_thresholds",
    "rows",
    "status_counts",
    "lookup_substituted_rows",
    "holiday_calendar_until",
    "topology_gaps",
    "generated_at",
)

OUTPUT_COLS = [
    "date",
    "station_no",
    "station_name",
    "line",
    "direction",
    "time_slot_30min",
    "time_slot",
    "congestion_pct",
    "grade",
    "data_status",
    "boarding_pred",
    "alighting_pred",
    "pred_source",
    "boarding_lookup",
    "alighting_lookup",
    "actual_boarding",
    "actual_alighting",
    "train_capacity",
]


def station_table(panel: pd.DataFrame) -> pd.DataFrame:
    return panel[["station_no", "station_name", "line", "lat", "lon"]].drop_duplicates("station_no")


def build_target_skeleton(
    panel: pd.DataFrame,
    target_date: pd.Timestamp,
    holidays: pd.DataFrame,
    events: pd.DataFrame | None,
) -> pd.DataFrame:
    """대상 날짜의 (역 × 20슬롯) 골격. 패널에 그 날이 있으면 패널 행을 쓴다."""
    existing = panel[panel["date"] == target_date]
    if len(existing):
        return existing.copy()

    stations = station_table(panel)
    grid = stations.merge(pd.DataFrame({"time_slot": SLOT_ORDER}), how="cross")
    grid["date"] = target_date
    grid = attach_calendar(grid, holidays)
    for t in TARGETS:
        grid[t] = np.nan
    if events is not None:
        grid = grid.merge(events, on=["date", "station_no"], how="left")
    for col in EVENT_COUNT_COLS:
        grid[col] = grid[col].fillna(0).astype(int) if col in grid.columns else 0
    for col in EVENT_NUMERIC_COLS:
        if col not in grid.columns:
            grid[col] = np.nan
    return grid


def resolve_predictor(kind: str, panel_train: pd.DataFrame, settings) -> Predictor:
    """설정값 → 예측기. `auto`는 최신 **lightgbm** 아티팩트가 있으면 그것, 없으면 lookup.

    `auto`가 `model_kind`를 보지 않고 폴더명 최신을 잡으면 144가 DL 아티팩트를 만든 순간 운영
    기본값이 조용히 바뀐다 — `latest_artifact(kind=...)`로 계열을 고정한다. DL 채택 판정은 145다.

    `dl`은 `latest_artifact`(이름 정렬)를 쓰지 않는다(197 B-3) — DL 변형이 18개라 이름 정렬 최신은
    채택 구성이 아니라 우연히 이름이 뒤에 오는 다른 변형(예: `dl_lstm_*`)을 고른다. 대신
    `settings.crowd_dl_artifact`로 폴더명을 고정한다.
    """
    if kind == "auto":
        art = latest_artifact(settings.crowd_models_dir, kind="lightgbm")
        if art:
            return build_predictor("lightgbm", artifact_dir=art)
        kind = "lookup"
    if kind == "dl":
        art = Path(settings.crowd_models_dir) / settings.crowd_dl_artifact
        if not art.exists():
            raise FileNotFoundError(
                f"DL 배포 아티팩트가 없다: settings.crowd_dl_artifact={settings.crowd_dl_artifact!r} "
                f"기대 경로={art} — 이름 정렬(latest_artifact)로 고르지 않는다(197 B-3). 학습을 "
                "먼저 돌리거나 설정값을 실제 폴더명에 맞춘다"
            )
        found_kind = artifact_kind(art)
        if found_kind != "dl":
            raise ValueError(
                f"settings.crowd_dl_artifact={settings.crowd_dl_artifact!r}({art})의 "
                f"model_kind가 'dl'이 아니라 {found_kind!r}다 — 설정값이 잘못된 폴더를 가리킨다"
            )
        return build_predictor("dl", artifact_dir=art)
    if kind == "lightgbm":
        art = latest_artifact(settings.crowd_models_dir, kind=kind)
        if art is None:
            raise FileNotFoundError(
                f"{kind} 아티팩트가 없다: {settings.crowd_models_dir} — 학습을 먼저 돌린다"
            )
        return build_predictor(kind, artifact_dir=art)
    if kind == "lookup":
        return build_predictor("lookup", train_panel=panel_train)
    if kind == "llm":
        return build_predictor(
            "llm", api_key=settings.crowd_llm_api_key, model=settings.crowd_llm_model
        )
    raise ValueError(f"알 수 없는 예측기: {kind}")


def fixed_predictor_factory(predictor: Predictor) -> Callable[[str], Predictor]:
    """예측기 하나를 고정해 쓰는 팩토리.

    라우팅을 쓰지 않고 특정 계열로 재현할 때 쓴다(검증 스크립트·디버그). `predict_day`에
    `override_kind=predictor.kind`와 함께 넘기면 정책을 타지 않고 그 예측기가 그대로 쓰인다.
    """
    return lambda _kind: predictor


def predict_day(
    predictor_factory: Callable[[str], Predictor],
    panel: pd.DataFrame,
    target_date: pd.Timestamp,
    segments: list[dict],
    holidays: pd.DataFrame,
    events: pd.DataFrame | None,
    *,
    override_kind: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    """대상 날짜 한 날의 승하차 예측(대상 날짜 행만). 메타(가용성·라우팅 등)도 돌려준다.

    예측기를 직접 받지 않고 **`kind -> Predictor` 팩토리**를 받는다 — 라우팅이 정한 kind가 날짜마다
    다를 수 있고, 필요한 kind만 만들어야 하기 때문이다(`full`인 날 DL을 올리지 않는다). 팩토리는
    보통 `run()`이 캐시를 곁들여 넘긴다(같은 kind면 재사용).

    `override_kind`를 주면 라우팅을 건너뛰고 그 kind로 고정한다(디버그·재현용) — 이때
    meta의 `routing_rule`은 `None`, `predictor_override`는 `True`다. 주지 않으면
    `routing.availability()` → `routing.select(routing.POLICY, ...)`로 그날의 kind를 정한다
    (145 판정, `routing.py` 참고). **옛 `predictor_fallback="no_history"`(이력 전무 시 lookup 강제
    대체) 의미는 없어졌다** — `no_lag`도 라우팅이 정한 예측기(현재 GRU)를 쓴다. 그래도 BE가 이미
    읽는 필드라 meta 키 자체는 유지하고 값을 `None`으로 둔다.
    """
    target_date = pd.Timestamp(target_date).normalize()
    # 가용성 판정은 항상 HISTORY_DAYS(7일) 창 기준이다 — D-1·D-7 존재 여부만 보면 되고, 라우팅이
    # 예측기(그리고 그 required_history_days)를 정하기 *전에* 필요하다.
    probe = panel[
        (panel["date"] >= target_date - pd.Timedelta(days=HISTORY_DAYS))
        & (panel["date"] < target_date)
    ]
    probe_dates = set(probe["date"].unique())
    lag1d_available = (target_date - pd.Timedelta(days=1)) in probe_dates
    lag7d_available = (target_date - pd.Timedelta(days=7)) in probe_dates
    avail = routing.availability(lag1d_available, lag7d_available)

    if override_kind is not None:
        kind = override_kind
        routing_rule: dict | None = None
        predictor_override = True
    else:
        rule = routing.match_rule(routing.POLICY, avail=avail)
        kind = rule.pred
        routing_rule = routing.describe_policy([rule])[0]
        predictor_override = False

    predictor = predictor_factory(kind)
    # 창 길이는 예측기가 정한다 — DL(시퀀스)은 seq_days(기본 14)가 필요하고 lookup·LightGBM은 7일이다.
    history_days = max(HISTORY_DAYS, getattr(predictor, "required_history_days", HISTORY_DAYS))
    history = panel[
        (panel["date"] >= target_date - pd.Timedelta(days=history_days))
        & (panel["date"] < target_date)
    ]
    have_dates = set(history["date"].unique())
    target = build_target_skeleton(panel, target_date, holidays, events)
    window = pd.concat([history, target], ignore_index=True, sort=False)
    pred = predictor.predict(window, segments)
    pred = pred[pred["date"] == target_date].reset_index(drop=True)

    meta = {
        "target_date": str(target_date.date()),
        "in_panel": bool(len(panel[panel["date"] == target_date])),
        "history_window_days": int(history_days),
        "history_days_present": len(have_dates),
        "history_dates": sorted(str(pd.Timestamp(d).date()) for d in have_dates),
        "lag1d_available": lag1d_available,
        "lag7d_available": lag7d_available,
        "availability": avail,
        "routing_rule": routing_rule,
        "predictor_override": predictor_override,
        "predictor": predictor.kind,
        "predictor_version": predictor.version,
        "predictor_fallback": None,
    }
    out = target[
        ["date", "station_no", "station_name", "line", "time_slot", "day_type", *TARGETS]
    ].merge(pred, on=["date", "station_no", "time_slot"], how="left")
    return out, meta


def to_congestion_table(
    predicted: pd.DataFrame,
    segments: list[dict],
    capacity: dict,
    calibration: pd.DataFrame,
    thresholds: list[float],
    holiday_fallback: str | None = HOLIDAY_FALLBACK_DAY_TYPE,
) -> pd.DataFrame:
    """승하차 예측 → 30분 보정 혼잡도·등급·상태 표(OUTPUT_COLS).

    `holiday_fallback=None`으로 부르면 146 이전 동작(1~8호선 공휴일 전체가 `no_calibration`)이 나온다 —
    전후 비교용이다(`validation/CROWD/congestion-criteria-check/diagnose.py`).

    모델 예측이 음수인 셀은 그 타깃의 lookup 값(`{target}_lookup`)으로 대체한다(197 B-2) — 145
    `family-check/RESULTS.md` 7절에서 모델이 음수를 낸 셀은 lookup이 더 정확했다(RMSE `no_lag`
    90.46→69.85, `d7_only` 53.86→27.18). lookup도 없거나(NaN) 음수면 최종 하한으로 0을 쓴다
    (lookup 자체가 음수일 수는 없으니 이 경로는 사실상 "lookup 결측" 케이스다). 대체 여부는 `pred_source`
    (`model`/`lookup_negative`)로 노출한다 — 인원 ≥ 0은 물리 제약이라 대체 자체는 원칙 8("값을 채우지
    않는다")과 무관하고, 여전히 채우지 않는 것은 `congestion_pct`·`grade`의 NaN(배율표·기준선 결측)뿐이다.
    """
    board = predicted.copy()
    was_negative = pd.Series(False, index=board.index)
    for t in TARGETS:
        raw_pred = board[f"{t}_pred"].to_numpy(dtype=float)
        lookup_val = board[f"{t}_lookup"].to_numpy(dtype=float)
        negative = raw_pred < 0  # NaN은 False — 결측(예측 불가)은 그대로 NaN으로 둔다(원칙 8)
        substituted = raw_pred.copy()
        substituted[negative] = lookup_val[negative]
        still_bad = negative & (np.isnan(substituted) | (substituted < 0))
        substituted[still_bad] = 0.0
        board[t] = substituted  # recursive_congestion 입력(승하차) — 이 컬럼명을 쓴다
        was_negative |= negative
    # 출력 *_pred도 같은 board[t] 값을 그대로 쓴다(per_row) — 대체를 두 번 계산하지 않는다.
    board["pred_source"] = np.where(was_negative.to_numpy(), "lookup_negative", "model")
    raw = recursive_congestion(board, segments, capacity)
    day_type = predicted[["date", "station_no", "day_type"]].drop_duplicates(["date", "station_no"])
    raw = raw.merge(day_type, on=["date", "station_no"], how="left")
    cal = apply_calibration(raw, calibration, holiday_fallback)
    cal["grade"] = grade(cal["congestion_pct_calibrated"], thresholds)

    per_row = (
        board[
            [
                "date",
                "station_no",
                "time_slot",
                "station_name",
                "boarding",
                "alighting",
                "boarding_lookup",
                "alighting_lookup",
                "pred_source",
            ]
        ]
        .rename(columns={"boarding": "boarding_pred", "alighting": "alighting_pred"})
        .merge(
            predicted.rename(
                columns={"boarding": "actual_boarding", "alighting": "actual_alighting"}
            )[["date", "station_no", "time_slot", "actual_boarding", "actual_alighting"]],
            on=["date", "station_no", "time_slot"],
            how="left",
        )
    )
    out = cal.merge(per_row, on=["date", "station_no", "time_slot"], how="left")
    out = out.rename(columns={"congestion_pct_calibrated": "congestion_pct"})
    # 재귀식·배율 부동소수 잔차로 −1e-13 수준의 음수가 나온다(2026-09-13 표에서 20행). 값 왜곡이
    # 아니라 표현 오차이고, 소비자(BE `congestion.level`)가 0 이상을 가정하므로 하한을 0으로 맞춘다.
    # NaN은 그대로 둔다 — 그건 배율표 결측이고 채우지 않는다(원칙 8).
    out["congestion_pct"] = out["congestion_pct"].clip(lower=0.0)
    missing = out["congestion_pct"].isna().to_numpy()
    boundary = (
        pd.MultiIndex.from_arrays([out["station_no"], out["direction"]])
        .isin(list(truncated_boundary_cells(segments)))
        .astype(bool)
    )
    status = np.where(out["boarding_lookup"].isna(), "no_lookup", "ok")
    status = np.where(
        (status == "ok") & out["calibration_fallback"].fillna(False).to_numpy(),
        "calibration_fallback",
        status,
    )
    status = np.where((status == "ok") & missing & boundary, "segment_truncated", status)
    status = np.where((status == "ok") & missing, "no_calibration", status)
    out["data_status"] = status
    unknown = sorted(set(status.tolist()) - set(DATA_STATUS_VALUES))
    if unknown:
        raise RuntimeError(
            f"문서화되지 않은 data_status: {unknown} — DATA_STATUS_VALUES와 "
            "SERVING_CONTRACT.md 2절을 같이 고쳐라"
        )
    return out.reindex(columns=OUTPUT_COLS)


def validated_meta(meta: dict) -> dict:
    """`.meta.json`에 쓸 메타를 명세 키(`META_KEYS`)에 맞춰 검증·정렬한다.

    키를 추가·삭제하면서 `META_KEYS`와 `SERVING_CONTRACT.md` 3절을 안 고치면 **배치가 여기서 멈춘다.**
    조용히 빠뜨리거나 문서에 없는 키가 BE에 흘러가는 것보다 낫다(197 C부).
    """
    missing = [k for k in META_KEYS if k not in meta]
    extra = [k for k in meta if k not in META_KEYS]
    if missing or extra:
        raise RuntimeError(
            f"메타 키가 명세와 어긋난다 — 누락 {missing} / 미문서화 {extra}. "
            "META_KEYS와 SERVING_CONTRACT.md 3절을 같이 고쳐라"
        )
    return {k: meta[k] for k in META_KEYS}


def run(
    target_dates: list[pd.Timestamp],
    predictor_kind: str | None = None,
    out_dir: Path | None = None,
    use_recent: bool = True,
) -> list[Path]:
    settings = get_settings()
    out_dir = Path(out_dir or settings.crowd_serving_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    panel = load_panel(with_events=True)
    holidays = load_holidays()
    events_path = CROWD_PROCESSED / EVENTS_NAME
    events = pd.read_parquet(events_path) if events_path.exists() else None
    # 143: D−1 수집기가 쌓은 최근 실측을 패널 뒤에 이어 붙여 이력 창(시차 피처)을 채운다. 파일이 없으면 패널만.
    recent_dates: list[str] = []
    recent = load_recent_long() if use_recent else None
    if recent is not None:
        panel, recent_dates = extend_panel_with_recent(panel, recent, holidays, events)
        print(
            f"[배치] 최근 실측 {len(recent_dates)}일 이어붙임: {recent_dates[:1]} ~ {recent_dates[-1:]}",
            flush=True,
        )
    segments, gaps = resolved_segments(panel)
    capacity = load_capacity()
    calibration = pd.read_parquet(CROWD_PROCESSED / CALIBRATION_NAME)
    thresholds = settings.grade_thresholds

    # --predictor CLI가 명시되면 라우팅을 건너뛰고 그 kind 하나로 전 날짜를 예측한다(디버그·재현용).
    # CLI가 없으면(None) settings.crowd_predictor 기본값 "auto"는 라우팅에 맡긴다는 뜻이다 — 누군가
    # .env에서 그 값을 다른 kind로 고정해 뒀다면 그것도 명시적 override로 본다.
    override_kind = predictor_kind or (
        settings.crowd_predictor if settings.crowd_predictor != "auto" else None
    )
    predictor_cache: dict[str, Predictor] = {}

    def get_predictor(kind: str) -> Predictor:
        # 같은 kind는 재사용한다 — run()이 매 날짜마다 아티팩트를 다시 로드하지 않는다.
        if kind not in predictor_cache:
            predictor_cache[kind] = resolve_predictor(kind, panel, settings)
        return predictor_cache[kind]

    written = []
    for d in target_dates:
        d = pd.Timestamp(d).normalize()
        predicted, meta = predict_day(
            get_predictor, panel, d, segments, holidays, events, override_kind=override_kind
        )
        table = to_congestion_table(predicted, segments, capacity, calibration, thresholds)
        path = out_dir / f"predictions_{d:%Y-%m-%d}.parquet"
        table.to_parquet(path, index=False)
        meta.update(
            {
                "recent_dates_available": recent_dates,
                "grade_thresholds": thresholds,
                "rows": len(table),
                "status_counts": table["data_status"].value_counts().to_dict(),
                "lookup_substituted_rows": int((table["pred_source"] == "lookup_negative").sum()),
                "holiday_calendar_until": (
                    str(holiday_coverage_end(holidays).date())
                    if holiday_coverage_end(holidays) is not None
                    else None
                ),
                "topology_gaps": gaps.to_dict("records") if len(gaps) else [],
                "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
            }
        )
        path.with_suffix(".meta.json").write_text(
            json.dumps(validated_meta(meta), ensure_ascii=False, indent=1, default=str),
            encoding="utf-8",
        )
        print(
            f"[배치] {d:%Y-%m-%d} → {path.name} ({len(table):,}행, {meta['predictor_version']}, "
            f"이력 {meta['history_days_present']}일, 상태 {meta['status_counts']})",
            flush=True,
        )
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--date", action="append", default=[], help="YYYY-MM-DD (여러 번 가능)")
    ap.add_argument("--today", action="store_true")
    ap.add_argument("--tomorrow", action="store_true")
    ap.add_argument("--predictor", default=None, help="auto|lookup|lightgbm|dl|llm (기본: 설정값)")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument(
        "--no-recent", action="store_true", help="D−1 수집 파일을 이어붙이지 않는다(패널만)"
    )
    args = ap.parse_args(argv)

    today = pd.Timestamp.now().normalize()
    dates = [pd.Timestamp(x) for x in args.date]
    if args.today:
        dates.append(today)
    if args.tomorrow:
        dates.append(today + pd.Timedelta(days=1))
    if not dates:
        ap.error("--date, --today, --tomorrow 중 하나는 필요하다")
    run(
        dates,
        args.predictor,
        Path(args.out_dir) if args.out_dir else None,
        use_recent=not args.no_recent,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
