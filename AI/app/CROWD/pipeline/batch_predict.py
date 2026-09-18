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
- **패널에 없는 날짜**(오늘·내일 — 실제 운영): 역 × 20슬롯 골격을 만들고 달력에서 day_type,
  `settings.crowd_events_files`에 나열된 이벤트 표들(콤마 구분, `load_event_tables`, 200)에서 경기·
  축제를 붙인다. 학습(`dataset.EVENTS_NAME`)은 2024_2025 표 하나만 쓰지만, 서빙은 대상 날짜가
  2026 이후로 넘어가므로 그 구간을 덮는 표(예: `crowd_station_events_2026_2026.parquet`)를 뒤에
  이어 붙인다 — 같은 (date, station_no)는 뒤 파일이 덮어쓴다. 어느 표도 그 날짜를 덮지 않으면
  경기·축제 칸은 그대로 0으로 채워지는데(원칙 8과 무관 — "이벤트가 없었다"의 0-채움 자체는
  유지한다), 그 사실을 meta의 `events_coverage_end`(표들의 최대 date)·`events_available`(대상
  날짜가 그 안에 있는지)로 노출한다. 승하차는 NaN으로 둔다. 시차 피처는 창에 든 과거 행에서
  채워진다. 패널(연간 CSV, 2025-12까지) 뒤에는 D−1 수집기(`DATA_ENGINE/collect/subway_ridership_daily.py`)가 쌓은
  `data/CROWD/interim/crowd_recent_ridership_long.parquet`을 이어 붙여 이력 창을 채운다(143). 내일은 `lag1d`
  (전날)가 비어 `lag7d`만으로 예측되는데 이 사실을 `lag1d_available`로 표시한다.

## 가용성별 예측기 라우팅(197, 145 후속 갱신) — `routing.py`

이력 완비(`full`)/결손(`d1_only`·`d7_only`)/전무(`no_lag`)에 따라 쓰는 예측기가 다르다 — 145 후속
`masking-check/RESULTS.md` 14절 판정으로 `full`·`d7_only`·`no_lag`는 마스킹 학습 LightGBM,
`d1_only`만 GRU(dl)다(197 당시는 결손·전무 전부 GRU였다). `predict_day`가 `routing.availability()` →
`routing.select()`로 그날의 kind를 정하고, `run()`이 필요한 예측기만 지연 로드해 같은 kind는
재사용한다. **`no_lag`도 LightGBM 대신 lookup으로 조용히 넘어가던 옛 fallback은 없어졌다** — 지금은
`no_lag`도 라우팅이 정한 예측기(마스킹 LightGBM)를 쓰고, 그 사실이 meta의 `availability`·
`routing_rule`에 남는다. `--predictor` CLI로 kind를 명시하면 라우팅을 건너뛰고 그 kind 하나로 전
날짜를 예측한다(디버그·재현용) — 이때 `routing_rule`은 `null`, `predictor_override`는 `true`다.

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
    python -m app.CROWD.pipeline.batch_predict --date 2025-06-02 --trains    # 열차·노드 표도 산출(239, 옵션)

## 열차·노드 표(239, 옵션) — `predictions_train_{date}.parquet`

`settings.crowd_train_table`(또는 `--trains`/`--no-trains`)를 켜면 같은 슬롯 표에서 열차 한 대 ×
역 한 개 단위의 표를 추가로 만든다. **예측이 아니라 분해**다(`RESOLUTION_LADDER.md` §1.1·§4) — 슬롯
혼잡도의 총량을 시각표(`timetable.py`)로 나누고 열차 궤적을 노드로 재색인할 뿐 새 정보를 만들지
않는다. 기본은 꺼짐 — BE 적재 경로가 정해지기 전까지 기존 산출물·메타 값을 바꾸지 않는다. 컬럼·
메타 키는 `SERVING_CONTRACT.md` 7절·3절, 구현은 `to_train_table`(`timetable.py`·`disaggregate.py`
3층 함수를 잇는다).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
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
    extend_panel_with_recent,
    load_panel,
    load_recent_long,
    resolved_segments,
)
from app.CROWD.pipeline.disaggregate import (
    MIX_H0_DEFAULT,
    MIX_H1_DEFAULT,
    allocate_flows_to_trains,
    allocate_to_trains,
    node_states,
    split_hourly_to_30min,
    train_trajectory,
)
from app.CROWD.pipeline.features import SLOT_ORDER
from app.CROWD.pipeline.lookup import TARGETS
from app.CROWD.pipeline.predictor import (
    Predictor,
    artifact_kind,
    build_predictor,
    latest_artifact,
)
from app.CROWD.pipeline.timetable import (
    assign_links,
    load_timetable,
    segment_links,
    segment_pairs,
    timetable_day_type,
    timetable_version,
    trains_per_slot,
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

# `.meta.json`에 실리는 키와 그 순서. `predict_day`가 만드는 앞쪽 13개 + `run`이 덧붙이는
# 15개(200에서 8→10, 239에서 열차·노드 표 메타 5개를 `generated_at` 앞에 추가해 10→15).
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
    "events_coverage_end",
    "events_available",
    "grade_thresholds",
    "rows",
    "status_counts",
    "lookup_substituted_rows",
    "holiday_calendar_until",
    "topology_gaps",
    "train_table",
    "timetable_version",
    "train_rows",
    "headway_long_rows",
    "train_mass_gap",
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

# 239 — 열차·노드 표(`predictions_train_{date}.parquet`, 옵션)의 컬럼과 순서.
# `SERVING_CONTRACT.md` 7절과 짝이고 `test_crowd_serving_contract.test_train_output_columns_match_contract_table`가
# 대조한다.
TRAIN_OUTPUT_COLS = [
    "date",
    "station_no",
    "station_name",
    "line",
    "direction",
    "segment",
    "to_station_no",
    "prev_station_no",
    "train_id",
    "run_id",
    "pass_time",
    "express",
    "time_slot_30min",
    "headway_min",
    "headway_long",
    "mix_w",
    "share",
    "load_arr_est",
    "load_dep_est",
    "onboard_arr_est",
    "onboard_dep_est",
    "boarding_train_est",
    "alighting_train_est",
    "grade_dep",
    "arr_source",
    "link_ambiguous",
    "data_status",
    "pred_source",
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


def _lightgbm_artifact(settings) -> Path | None:
    """설정값 → LightGBM 배포 아티팩트 경로(145 후속). `resolve_predictor`의 `auto`·`lightgbm`
    분기가 함께 쓴다.

    `settings.crowd_lgbm_artifact`가 있으면 그 폴더명을 고정으로 쓴다(DL과 같은 방식, 197 B-3) —
    없으면 `FileNotFoundError`, `model_kind`가 lightgbm이 아니면 `ValueError`로 막는다. 설정값이
    `None`이면 이름 정렬 최신(`latest_artifact(kind="lightgbm")`, 없으면 `None`)으로 떨어진다.
    """
    if settings.crowd_lgbm_artifact is None:
        return latest_artifact(settings.crowd_models_dir, kind="lightgbm")
    art = Path(settings.crowd_models_dir) / settings.crowd_lgbm_artifact
    if not art.exists():
        raise FileNotFoundError(
            "LightGBM 배포 아티팩트가 없다: settings.crowd_lgbm_artifact="
            f"{settings.crowd_lgbm_artifact!r} 기대 경로={art} — 이름 정렬(latest_artifact)로 "
            "고르지 않는다(145 후속). 학습을 먼저 돌리거나 설정값을 실제 폴더명에 맞춘다"
        )
    found_kind = artifact_kind(art)
    if found_kind != "lightgbm":
        raise ValueError(
            f"settings.crowd_lgbm_artifact={settings.crowd_lgbm_artifact!r}({art})의 "
            f"model_kind가 'lightgbm'이 아니라 {found_kind!r}다 — 설정값이 잘못된 폴더를 가리킨다"
        )
    return art


def resolve_predictor(kind: str, panel_train: pd.DataFrame, settings) -> Predictor:
    """설정값 → 예측기. `auto`는 고정된(또는 이름 정렬 최신) **lightgbm** 아티팩트가 있으면 그것,
    없으면 lookup.

    `auto`가 `model_kind`를 보지 않고 폴더명 최신을 잡으면 144가 DL 아티팩트를 만든 순간 운영
    기본값이 조용히 바뀐다 — `latest_artifact(kind=...)`로 계열을 고정한다. DL 채택 판정은 145,
    LightGBM 배포판을 이름으로 고정(마스킹 학습 아티팩트)한 것은 145 후속이다.

    `lightgbm`도 `dl`처럼 `settings.crowd_lgbm_artifact`로 폴더명을 고정한다(145 후속, 아래
    `_lightgbm_artifact`) — 마스킹 학습 아티팩트가 이름 정렬에서 우연히 최신으로 잡히는 것과
    무관하게 명시로 고정해 운에 맡기지 않는다. 설정값이 `None`이면 예전처럼
    `latest_artifact(kind="lightgbm")`(이름 정렬 최신)로 떨어진다.

    `dl`은 `latest_artifact`(이름 정렬)를 쓰지 않는다(197 B-3) — DL 변형이 18개라 이름 정렬 최신은
    채택 구성이 아니라 우연히 이름이 뒤에 오는 다른 변형(예: `dl_lstm_*`)을 고른다. 대신
    `settings.crowd_dl_artifact`로 폴더명을 고정한다.
    """
    if kind == "auto":
        art = _lightgbm_artifact(settings)
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
        art = _lightgbm_artifact(settings)
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
    (145 후속 `masking-check` 판정, `routing.py` 참고). **옛 `predictor_fallback="no_history"`(이력
    전무 시 lookup 강제 대체) 의미는 없어졌다** — `no_lag`도 라우팅이 정한 예측기(현재 마스킹
    LightGBM)를 쓴다. 그래도 BE가 이미 읽는 필드라 meta 키 자체는 유지하고 값을 `None`으로 둔다.
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


def _congestion_table_full(
    predicted: pd.DataFrame,
    segments: list[dict],
    capacity: dict,
    calibration: pd.DataFrame,
    thresholds: list[float],
    holiday_fallback: str | None = HOLIDAY_FALLBACK_DAY_TYPE,
) -> pd.DataFrame:
    """`to_congestion_table`의 몸통 — `OUTPUT_COLS`로 추리기 전 전체 프레임을 돌려준다(239).

    `segment`·`day_type`·`calibration_fallback` 등 슬롯 표 계약(`OUTPUT_COLS`)에는 없지만
    `to_train_table`(열차·노드 표)이 필요로 하는 중간 컬럼을 그대로 남긴다. `to_congestion_table`은
    이 함수의 결과를 `reindex`만 해서 반환하므로 공개 동작은 이전과 완전히 같다.
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
    return out


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
    return _congestion_table_full(
        predicted, segments, capacity, calibration, thresholds, holiday_fallback
    ).reindex(columns=OUTPUT_COLS)


def to_train_table(
    full_table: pd.DataFrame,
    timetable: pd.DataFrame,
    segments: list[dict],
    calibration: pd.DataFrame,
    thresholds: list[float],
    *,
    mix_h0: float | None = MIX_H0_DEFAULT,
    mix_h1: float = MIX_H1_DEFAULT,
) -> tuple[pd.DataFrame, dict]:
    """슬롯 표(`_congestion_table_full`의 대상 날짜 한 날치 결과) → 열차·노드 표(239, 옵션).

    `RESOLUTION_LADDER.md` §1.1·§3 L4·L5가 설계한 분해를 그대로 코드로 잇는다 — **예측이 아니라
    분해**라 새 정보를 만들지 않는다(원칙 4·8). `full_table`은 대상 날짜 하나짜리
    `_congestion_table_full` 출력(`segment`·`day_type`·`calibration_fallback` 등 reindex 이전
    컬럼이 남아 있어야 한다), `timetable`은 `timetable.load_timetable` 출력(전 요일유형),
    `calibration`은 배율표(1층 `split_hourly_to_30min`의 30분 비중 산출에 쓰인다).

    단계:
    1. `segment_links`로 위상(`adjacency`·`link_segments`)을 먼저 얻는다. 대상 날짜의 패널
       요일유형을 시각표 요일유형으로 바꿔(`timetable.timetable_day_type`) 그 요일유형 시각표만
       남기고, `disaggregate.train_trajectory`로 열차 궤적(런·직전/다음 역)을 구한 뒤
       `timetable.assign_links`로 정차마다 실제 링크(`link_id`)를 배정한다 — 강동처럼 한 역이
       여러 세그먼트에 걸칠 때 그 열차가 실제로 지나온·갈 세그먼트로 미리 하나만 고르는 것이다
       (135 버그 수정: 예전에는 링크를 정하기 *전에* 슬롯을 배분해 여러 세그먼트가 열차 수·질량을
       나눠 가졌다). 링크가 아예 안 잡히는 행(토폴로지 결번)은 버리고 `stats["trains_without_link"]`
       로 센다.
    2. 슬롯 재차인원 `onboard_30min_est = congestion_pct/100 × train_capacity × n_trains`를
       만든다(88의 정의 그대로 — 공식 혼잡도는 "그 슬롯 열차들의 평균"이다). `n_trains`는 이제
       `timetable.trains_per_slot(..., extra_key=("link_id",))`로 **링크별로** 센다 — 링크가 다르면
       같은 역·방향·슬롯이라도 다른 슬롯으로 취급해야 그 링크를 실제로 지나는 열차 수만 반영한다.
       열차가 없는 슬롯은 `n_trains`가 NaN이라 이 값도 NaN이고, 뒤에서 그 슬롯은 배분 대상에서
       빠진다(`stats["slots_without_trains"]`로 셀 수를 남긴다 — 채우지 않는다, 원칙 8).
    3. `disaggregate.allocate_to_trains`에 `extra_key=("link_id",)`를 주어 슬롯 재차인원을
       열차에 배분하고(2층, 링크별로 몫·질량을 따로 보존), `disaggregate.node_states`로 열차
       궤적을 역(노드) 관점으로 재색인한다(L5). 1단계에서 이미 링크를 하나로 정했으므로
       `node_states`의 중복 해소(`_resolve_link_duplicates`)는 안전망으로만 작동한다(정상 입력에서는
       중복이 없다). `assign_links`가 매긴 `link_ambiguous`(`_link_ambiguous_assign`로 임시 보관)와
       `node_states`가 매긴 `link_ambiguous`를 OR로 합쳐 최종 컬럼을 만든다 — 둘 중 하나라도
       모호했으면 숨기지 않는다(원칙 8).
    4. 방향 없는 역 단위 30분 승하차(1층, `disaggregate.split_hourly_to_30min`)를
       `disaggregate.allocate_flows_to_trains`로 같은 슬롯의 모든 방향·열차에 나눈다. 1~8호선
       공휴일처럼 그 날짜 요일유형이 배율표에 없으면(`calibration["day_type"]`에 없으면) 비중
       조회에서만 `timetable_day_type`로 변환한 요일유형(예: 일요일)을 빌려 쓴다 —
       `congestion.HOLIDAY_FALLBACK_DAY_TYPE`과 같은 대체를 30분 비중 쪽에도 적용하는 것이다.
    5. `to_station_no`(= `next_station_no`)·`pass_time`(= `arrival_time`)·`grade_dep`을 붙이고
       `TRAIN_OUTPUT_COLS`로 추린 뒤 (line, station_no, direction, pass_time) 순으로 정렬한다.

    NaN은 상속만 한다 — 배율표 결측으로 슬롯 혼잡도가 NaN이면 그 슬롯의 모든 열차가
    `load_dep_est`·`grade_dep` NaN이고, `data_status`·`pred_source`는 슬롯 표 값을 그대로 쓴다.

    반환: `(train_tbl, stats)`. `stats`는 `train_rows`·`headway_long_rows`·`slots_without_trains`
    ·`train_mass_gap`(이제 `[date, station_no, direction, link_id, time_slot_30min]`별 슬롯
    재차인원 합과 열차 배분 합의 최대 절대오차, 링크별로 따로 잰다 — 질량 보존 확인용)
    ·`link_ambiguous_rows`·`trains_without_link`(토폴로지에 링크가 안 잡혀 버려진 열차-정차 행 수).
    """
    day_type_values = full_table["day_type"].dropna().unique()
    if len(day_type_values) != 1:
        raise ValueError(
            f"full_table의 day_type이 대상 날짜 하나에 값 {len(day_type_values)}개다: "
            f"{sorted(day_type_values)} — to_train_table은 한 날짜치 슬롯 표만 받는다"
        )
    day_type = day_type_values[0]
    day_type_tt = timetable_day_type(day_type)
    tt = timetable[timetable["day_type"] == day_type_tt]

    _, link_segments = segment_links(segments)
    # 도착 재차 이어붙임은 "연속 인접"이 아니라 "같은 세그먼트"면 허용한다 — 급행·정차 행 결측으로
    # 역을 건너뛴 열차도 사람을 싣고 가기 때문(`timetable.segment_pairs` docstring).
    adjacency = segment_pairs(segments)
    traj = assign_links(train_trajectory(tt), link_segments)
    trains_without_link = int(traj["link_id"].isna().sum())
    traj = traj.dropna(subset=["link_id"]).reset_index(drop=True)

    n_trains = trains_per_slot(traj, extra_key=("link_id",))

    slot_loads = full_table[
        [
            "date",
            "station_no",
            "station_name",
            "line",
            "direction",
            "segment",
            "time_slot_30min",
            "congestion_pct",
            "train_capacity",
            "data_status",
            "pred_source",
        ]
    ].copy()
    slot_loads["day_type"] = day_type_tt
    slot_loads["link_id"] = slot_loads["line"] + "/" + slot_loads["segment"]
    slot_loads = slot_loads.merge(
        n_trains,
        on=["station_no", "direction", "day_type", "link_id", "time_slot_30min"],
        how="left",
    )
    slot_loads["onboard_30min_est"] = (
        slot_loads["congestion_pct"] / 100.0 * slot_loads["train_capacity"] * slot_loads["n_trains"]
    )
    slots_without_trains = int(
        (slot_loads["n_trains"].isna() & slot_loads["congestion_pct"].notna()).sum()
    )

    train_rows = allocate_to_trains(
        slot_loads,
        traj,
        load_col="onboard_30min_est",
        mix_h0=mix_h0,
        mix_h1=mix_h1,
        extra_key=("link_id",),
    )
    # allocate_to_trains는 배분에 필요한 컬럼만 돌려준다 — 급행 여부·링크 모호 플래그는 궤적
    # 표(1단계에서 링크까지 정한 `traj`)에서 다시 붙인다(`DATA_ENGINE/eda/build_load_by_train.build`
    # 와 같은 처리를 링크 단위로 확장한 것).
    extra_cols = traj[
        [
            "station_no",
            "direction",
            "day_type",
            "link_id",
            "train_id",
            "arrival_time",
            "express",
            "link_ambiguous",
        ]
    ].rename(columns={"link_ambiguous": "_link_ambiguous_assign"})
    train_rows = train_rows.merge(
        extra_cols,
        on=["station_no", "direction", "day_type", "link_id", "train_id", "arrival_time"],
        how="left",
    )

    node_rows = node_states(
        train_rows, adjacency=adjacency, link_segments=link_segments, link_col="link_id"
    )
    # assign_links(1단계, 궤적 기반)와 node_states(안전망, 값 기반) 어느 쪽이 모호하다고 봤든
    # 숨기지 않는다(원칙 8) — OR로 합치고 임시 컬럼은 버린다.
    node_rows["link_ambiguous"] = node_rows["link_ambiguous"] | node_rows[
        "_link_ambiguous_assign"
    ].fillna(False)
    node_rows = node_rows.drop(columns=["_link_ambiguous_assign"])

    station_hour = (
        full_table[["date", "station_no", "time_slot", "boarding_pred", "alighting_pred"]]
        .drop_duplicates(subset=["date", "station_no", "time_slot"])
        .rename(columns={"boarding_pred": "boarding", "alighting_pred": "alighting"})
    )
    cal_day_types = set(calibration["day_type"].dropna().unique())
    station_hour["day_type"] = day_type if day_type in cal_day_types else day_type_tt
    slot_flows = split_hourly_to_30min(
        station_hour, calibration, value_cols=("boarding", "alighting")
    )
    flow_rows = allocate_flows_to_trains(slot_flows, node_rows, rule="share")

    flow_rows["grade_dep"] = grade(flow_rows["load_dep_est"], thresholds)
    flow_rows["to_station_no"] = flow_rows["next_station_no"].astype("Int64")
    flow_rows["prev_station_no"] = flow_rows["prev_station_no"].astype("Int64")
    flow_rows["run_id"] = flow_rows["run_id"].astype(int)
    flow_rows["pass_time"] = flow_rows["arrival_time"]

    train_tbl = (
        flow_rows.reindex(columns=TRAIN_OUTPUT_COLS)
        .sort_values(["line", "station_no", "direction", "pass_time"], kind="mergesort")
        .reset_index(drop=True)
    )

    # 링크(`link_id`)까지 키에 넣어야 강동처럼 한 역에 세그먼트가 겹칠 때도 각 링크의 질량을
    # 따로 확인할 수 있다 — 링크 없이 역·방향·슬롯만으로 인덱싱하면 세그먼트 수만큼 중복된
    # 인덱스끼리 빼는 꼴이 되어 오차가 부풀려진다(135 버그).
    dep_sum = flow_rows.groupby(
        ["date", "station_no", "direction", "link_id", "time_slot_30min"], observed=True
    )["onboard_dep_est"].sum()
    slot_totals = slot_loads.set_index(
        ["date", "station_no", "direction", "link_id", "time_slot_30min"]
    )["onboard_30min_est"]
    mass_diff = (dep_sum - slot_totals).dropna()
    train_mass_gap = float(mass_diff.abs().max()) if len(mass_diff) else 0.0

    stats = {
        "train_rows": len(train_tbl),
        "headway_long_rows": int(train_tbl["headway_long"].sum()),
        "slots_without_trains": slots_without_trains,
        "train_mass_gap": train_mass_gap,
        "link_ambiguous_rows": int(train_tbl["link_ambiguous"].sum()),
        "trains_without_link": trains_without_link,
    }
    return train_tbl, stats


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


def _atomic_write(write_fn: Callable[[Path], None], path: Path) -> None:
    """임시 파일에 `write_fn`으로 쓰고 `path`로 원자적 교체(`rename`)한다.

    FastAPI가 서빙 디렉터리를 상시로 읽으므로(197 인프라 핸드오프), 덮어쓰기 중간의 반쯤 쓰인
    파일을 볼 수 있으면 안 된다. 실패하면 임시 파일만 지우고 기존 `path`는 그대로 둔다.
    """
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        write_fn(tmp)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_event_tables(paths: Sequence[Path]) -> tuple[pd.DataFrame | None, pd.Timestamp | None]:
    """`settings.events_paths`에 나열된 이벤트 표들을 읽어 합친다(200) — 배치 서빙 전용.

    학습(`dataset.load_panel(with_events=True)`)은 `dataset.EVENTS_NAME` 표 하나만 읽는다 — 이
    함수와 무관하다. 없는 경로는 `[안내]`로 알리고 건너뛴다. 같은 (date, station_no) 키가 여러
    표에 있으면 **뒤 파일이 이긴다**(`crowd_events_files` 순서 — 나중 구간 표를 뒤에 둔다). 반환하는
    두 번째 값은 합친 표의 최대 date(이벤트 커버리지 종료일) — 아무 표도 못 읽으면 `(None, None)`.
    """
    frames = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            print(f"[안내] 이벤트 표 없음, 건너뜀: {path}", flush=True)
            continue
        frames.append(pd.read_parquet(path))
    if not frames:
        return None, None
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.drop_duplicates(subset=["date", "station_no"], keep="last").reset_index(
        drop=True
    )
    return combined, combined["date"].max()


def events_available(target_date: pd.Timestamp, coverage_end: pd.Timestamp | None) -> bool:
    """대상 날짜가 이벤트 표 커버리지 안에 있는지(200).

    `False`면 그 날짜의 경기·축제 칸은 "이벤트가 없었다"가 아니라 "표가 그 구간을 안 덮는다"는
    뜻이다(0-채움 자체는 유지 — 원칙 8이 막는 것은 기준선 값을 채우는 것이지, 이벤트 개수 0-채움이
    아니다). `coverage_end`가 `None`(읽은 표가 없음)이면 항상 `False`.
    """
    if coverage_end is None:
        return False
    return pd.Timestamp(target_date).normalize() <= pd.Timestamp(coverage_end).normalize()


def run(
    target_dates: list[pd.Timestamp],
    predictor_kind: str | None = None,
    out_dir: Path | None = None,
    use_recent: bool = True,
    train_table: bool | None = None,
) -> list[Path]:
    settings = get_settings()
    out_dir = Path(out_dir or settings.crowd_serving_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    panel = load_panel(with_events=True)
    holidays = load_holidays()
    events, events_coverage_end = load_event_tables(settings.events_paths)
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

    # 239: 열차·노드 표는 기본 꺼짐(설정값) — CLI(`--trains`/`--no-trains`)가 명시하면 그것을 따른다.
    use_trains = settings.crowd_train_table if train_table is None else train_table
    timetable = None
    timetable_ver: str | None = None
    if use_trains:
        timetable = load_timetable(settings.crowd_timetable_path)
        timetable_ver = timetable_version(settings.crowd_timetable_path)

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
        full = _congestion_table_full(predicted, segments, capacity, calibration, thresholds)
        table = full.reindex(columns=OUTPUT_COLS)
        path = out_dir / f"predictions_{d:%Y-%m-%d}.parquet"
        _atomic_write(lambda p, table=table: table.to_parquet(p, index=False), path)

        train_meta = {
            "train_table": bool(use_trains),
            "timetable_version": timetable_ver,
            "train_rows": None,
            "headway_long_rows": None,
            "train_mass_gap": None,
        }
        if use_trains:
            train_tbl, tstats = to_train_table(full, timetable, segments, calibration, thresholds)
            train_path = out_dir / f"predictions_train_{d:%Y-%m-%d}.parquet"
            _atomic_write(
                lambda p, train_tbl=train_tbl: train_tbl.to_parquet(p, index=False), train_path
            )
            train_meta.update(
                {
                    "train_rows": tstats["train_rows"],
                    "headway_long_rows": tstats["headway_long_rows"],
                    "train_mass_gap": tstats["train_mass_gap"],
                }
            )
            print(
                f"[배치] {d:%Y-%m-%d} → {train_path.name} ({tstats['train_rows']:,}행, "
                f"headway_long {tstats['headway_long_rows']}, "
                f"mass_gap {tstats['train_mass_gap']:.6f})",
                flush=True,
            )

        meta.update(
            {
                "recent_dates_available": recent_dates,
                "events_coverage_end": (
                    str(events_coverage_end.date()) if events_coverage_end is not None else None
                ),
                "events_available": events_available(d, events_coverage_end),
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
                **train_meta,
                "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
            }
        )
        meta_text = json.dumps(validated_meta(meta), ensure_ascii=False, indent=1, default=str)
        _atomic_write(
            lambda p, meta_text=meta_text: p.write_text(meta_text, encoding="utf-8"),
            path.with_suffix(".meta.json"),
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
    ap.add_argument(
        "--trains",
        dest="trains",
        action="store_true",
        default=None,
        help="열차·노드 표(predictions_train_*.parquet)도 산출한다(기본: settings.crowd_train_table)",
    )
    ap.add_argument(
        "--no-trains",
        dest="trains",
        action="store_false",
        help="열차·노드 표를 산출하지 않는다(설정값이 켜져 있어도 이번 실행만 끈다)",
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
        train_table=args.trains,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
