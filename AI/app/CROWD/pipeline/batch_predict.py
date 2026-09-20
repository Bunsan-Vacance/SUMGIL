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
    python -m app.CROWD.pipeline.batch_predict --date 2025-06-02 --link-table # 링크(from/to) 표도 산출(244, 옵션)
    python -m app.CROWD.pipeline.batch_predict --date 2025-06-02 --no-line9   # 9호선 lookup 편입 끄기(기본 켜짐)

## 열차·노드 표(239, 옵션) — `predictions_train_{date}.parquet`

`settings.crowd_train_table`(또는 `--trains`/`--no-trains`)를 켜면 같은 슬롯 표에서 열차 한 대 ×
역 한 개 단위의 표를 추가로 만든다. **예측이 아니라 분해**다(`RESOLUTION_LADDER.md` §1.1·§4) — 슬롯
혼잡도의 총량을 시각표(`timetable.py`)로 나누고 열차 궤적을 노드로 재색인할 뿐 새 정보를 만들지
않는다. 기본은 꺼짐 — BE 적재 경로가 정해지기 전까지 기존 산출물·메타 값을 바꾸지 않는다. 컬럼·
메타 키는 `SERVING_CONTRACT.md` 7절·3절, 구현은 `to_train_table`(`timetable.py`·`disaggregate.py`
3층 함수를 잇는다).

## 9호선 2·3단계 — lookup 기준선 전용 편입

9호선 2·3단계 13역(언주 4126~중앙보훈병원 4138)은 `settings.crowd_line9_serving`(기본 켜짐,
CLI `--line9`/`--no-line9`)이 켜져 있으면 슬롯·링크 표에 들어간다. **모델 추론에는 절대 넣지
않는다** — `station_no`가 학습 패널(1~8호선)에 0건이라 모델(`features.CATEGORICAL_COLS`)
기준으로는 미학습 범주가 되기 때문이다. 대신 `dataset.load_line9_panel`이 읽는 전용 패널
(`crowd_panel_line9_2025_2026.parquet`)에 `DayTypeLookupBaseline`을 그 자체로 fit해
day_type×station_no×time_slot 평균만으로 예측한다(`predict_line9_day`) — 라우팅·시차·이벤트
피처가 전혀 없다. 이 13역은 D−1 실시간 승하차 원천도 없어(`SERVING_CONTRACT.md` 노선 커버리지
절) `lag1d_available`과 무관하게 항상 이 경로를 탄다. 결과 행은 `pred_source="lookup_line9"`로
구분되고(`_congestion_table_full`), 토폴로지(`line_topology.yaml`의 9호선 "2·3단계" 세그먼트)가
패널에 들어오면서 `resolved_segments`가 그 세그먼트를 자동으로 채워 링크(from/to) 표(244)에도
같은 방식으로 편입된다 — 종합운동장(4130)↔봉은사(4129) 같은 링크가 별도 코드 없이 나온다.

## 링크(from/to) 표(244, 옵션) — `predictions_link_{date}.parquet` + BE CSV

`settings.crowd_link_table`(또는 `--link-table`/`--no-link-table`)를 켜면 슬롯 표에 (line, segment,
station_no, direction) → `to_station_no` 대응(세그먼트 위상에서 한 번만 계산)을 이너 조인해 링크
단위 표를 추가로 만들고, BE 적재용 CSV(`predictions_{date}_{HHMMSS}.csv` — parquet과 달리 `link_`
토큰이 없다, BE가 명시적으로 요청한 이름이다)도 같이 쓴다. **이것도 예측이 아니라 분해다**
(`RESOLUTION_LADDER.md` §1.1·§4) — 이너 조인이라 세그먼트 경계(종점·절단면)는 대응이 없어 자동으로
빠지고, 강동처럼 한 역이 여러 세그먼트에 걸치면 세그먼트마다 다른 `to_station_no`를 갖는 별개 행으로
남아 5.4절 강동 중복 문제가 자연히 풀린다 — 열차 표(239)의 `link_ambiguous` 같은 모호성 플래그가 이
표에는 없다(슬롯 집계 표라 여러 지선이 동시에 유효하다). CSV마다 같은 basename의 사이드카
`.meta.json`(`target_date`·`row_count`·`generated_at` 3키)이 같이 쓰인다 — 날짜당 하나뿐인 풍부한
`.meta.json`(3절)은 재생성 시 덮어써져 이전 CSV와 짝이 안 맞기 때문이다(8.1절). 기본은 꺼짐 — B-5
적재 계약(`.claude/handoff/response/FROME_BE-crowd-pred-load-path.md`)은 확정됐지만 배치 스케줄이
아직 등록되지 않았다. 컬럼·메타 키는 `SERVING_CONTRACT.md` 8절·3절, 구현은
`to_link_table`·`write_link_csv`.
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
    ASCENDING,
    CIRCULAR_LABELS,
    DESCENDING,
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
    load_line9_panel,
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
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
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

# 9호선 2·3단계 전용 표시값(위 "9호선 2·3단계" 절). 모델을 타지 않는 행이라 `pred_source`로
# 구분하고, `predictor_version`도 모델 아티팩트 이름이 아니라 lookup 판을 적는다 — 링크 표의
# `predictor_version`은 BE가 **행 단위**로 요청한 컬럼이라(`SERVING_CONTRACT.md` 8절) 모델
# 버전을 그대로 흘리면 "lightgbm이 만든 행"이라고 잘못 알려주게 된다.
LINE9_PRED_SOURCE = "lookup_line9"
LINE9_PREDICTOR_VERSION = "lookup:line9_2025_2026"

# `.meta.json`에 실리는 키와 그 순서. `predict_day`가 만드는 앞쪽 13개 + `run`이 덧붙이는
# 19개(200에서 8→10, 239에서 열차·노드 표 메타 5개를 `generated_at` 앞에 추가해 10→15, 244에서
# 링크 표 메타 2개를 같은 자리에 추가해 15→17, 9호선 lookup 편입에서 메타 2개를 같은 자리에
# 추가해 17→19).
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
    "link_table",
    "link_csv_rows",
    "line9_included",
    "line9_rows",
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

# 244 — 링크(from/to) 표(`predictions_link_{date}.parquet` + BE CSV, 옵션)의 컬럼과 순서.
# `SERVING_CONTRACT.md` 8절과 짝이고 `test_crowd_serving_contract.test_link_output_columns_match_contract_table`가
# 대조한다. `congestion_pct`는 parquet에서 이 이름 그대로다 — `level`로의 개명과 `time_slot`
# 0-47 인덱스 변환은 `write_link_csv`(BE CSV 전용)에서만 일어난다.
LINK_OUTPUT_COLS = [
    "date",
    "line",
    "from_station_no",
    "to_station_no",
    "direction",
    "time_slot_30min",
    "congestion_pct",
    "data_status",
    "pred_source",
    "predictor_version",
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


def predict_line9_day(
    line9_panel: pd.DataFrame,
    line9_lookup: DayTypeLookupBaseline,
    target_date: pd.Timestamp,
    holidays: pd.DataFrame,
) -> pd.DataFrame:
    """9호선 2·3단계 13역의 그 날 승하차 — **lookup 기준선만** 쓴다(모델에 절대 넣지 않는다).

    `predict_day`(라우팅 → 예측기 → 이력 창 → 이벤트)와 짝이지만 훨씬 단순하다 — station_no가
    학습 패널에 0건이라 모델(`features.CATEGORICAL_COLS`)에 넣으면 미학습 범주가 되므로,
    day_type×station_no×time_slot 조회 하나로 끝낸다. 라우팅·시차 피처·이벤트가 없어 이력
    창도 필요 없다(9호선은 D−1 실시간 승하차 원천도 없다, `SERVING_CONTRACT.md` 노선 커버리지
    절). `line9_lookup`은 호출자(`run`)가 `line9_panel` 전체로 한 번 fit해 날짜마다 재사용한다.

    패널에 그 날짜가 있으면(2024-12-31~2026-01-31, 재현용) 실측 행을 그대로 쓰고, 없으면
    (실제 운영일) 13역 × 20슬롯 골격을 만들어 날짜만으로 day_type을 계산한다 — lookup 조회는
    day_type만 있으면 되므로 골격에 이벤트·기상 컬럼을 채울 필요가 없다.
    """
    target_date = pd.Timestamp(target_date).normalize()
    existing = line9_panel[line9_panel["date"] == target_date]
    if len(existing):
        target = existing.copy()
    else:
        grid = station_table(line9_panel).merge(
            pd.DataFrame({"time_slot": SLOT_ORDER}), how="cross"
        )
        grid["date"] = target_date
        grid = attach_calendar(grid, holidays)
        for t in TARGETS:
            grid[t] = np.nan
        target = grid

    pred = line9_lookup.predict(target)
    out = target[
        ["date", "station_no", "station_name", "line", "time_slot", "day_type", *TARGETS]
    ].copy()
    for t in TARGETS:
        out[f"{t}_lookup"] = pred[t].to_numpy()
        out[f"{t}_pred"] = pred[t].to_numpy()
    return out


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
    # 9호선 2·3단계는 애초에 모델에 넣지 않고 lookup만 쓰므로(위 "9호선 2·3단계" 절), 음수
    # 대체가 있었든 없었든 항상 `lookup_line9`로 구분한다 — `board["line"]`은 predicted(입력)의
    # 값이라 아래 recursive_congestion 이후에는 세그먼트(`seg["line"]`) 값으로 덮이므로 여기서
    # 미리 확정해 둔다.
    board["pred_source"] = np.where(
        board["line"].to_numpy() == "9호선", LINE9_PRED_SOURCE, board["pred_source"]
    )
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


def _link_targets(segments: list[dict]) -> pd.DataFrame:
    """세그먼트 위상 → `(line, segment, station_no, direction) -> to_station_no` 대응표(244).

    선형(비순환) 세그먼트에서 `역 목록[i]`의 `하선`(오름차순)은 `역 목록[i+1]`로, `상선`(내림차순)은
    `역 목록[i-1]`로 가는 링크다. `i+1`·`i-1`이 없는 경계(진짜 종점이든 `truncated: true`
    절단면이든 강동처럼 그 세그먼트 목록이 거기서 끝나는 분기점이든)는 대응이 없어 행을 만들지
    않는다 — 그 셀은 재귀식이 구조적으로 0을 내는 세그먼트 국소 인공물이라 링크로 못 쓴다
    (`congestion.truncated_boundary_cells` docstring 참고). 순환 세그먼트는 모든 역이 다음
    (`(i+1) % n`)·이전(`(i-1) % n`)을 다 가져 경계가 없고, 오름차순 인덱스 쪽 타깃은
    `CIRCULAR_LABELS[ASCENDING]`("내선"), 내림차순 쪽은 `CIRCULAR_LABELS[DESCENDING]`("외선")
    라벨을 받는다. `segment_loads`와 같은 기준으로 역이 2개 미만인 세그먼트는 건너뛴다.
    """
    rows: list[tuple[str, str, int, str, int]] = []
    for seg in segments:
        stations = seg["stations"]
        n = len(stations)
        if n < 2:
            continue
        line = seg["line"]
        segment = seg["segment"]
        if seg.get("circular"):
            asc_label = CIRCULAR_LABELS[ASCENDING]
            desc_label = CIRCULAR_LABELS[DESCENDING]
            for i in range(n):
                rows.append((line, segment, stations[i], asc_label, stations[(i + 1) % n]))
                rows.append((line, segment, stations[i], desc_label, stations[(i - 1) % n]))
        else:
            for i in range(n - 1):
                rows.append((line, segment, stations[i], ASCENDING, stations[i + 1]))
            for i in range(1, n):
                rows.append((line, segment, stations[i], DESCENDING, stations[i - 1]))
    return pd.DataFrame(
        rows, columns=["line", "segment", "station_no", "direction", "to_station_no"]
    )


def to_link_table(
    full_table: pd.DataFrame, segments: list[dict], predictor_version: str
) -> tuple[pd.DataFrame, dict]:
    """슬롯 표(`_congestion_table_full`의 대상 날짜 한 날치 결과) → 링크(from/to) 표(244, 옵션).

    **파생 뷰다, 새 정보가 아니다** — `full_table`에 이미 있는 값(`congestion_pct`·`data_status`
    등)을 링크 단위로 다시 보여줄 뿐이다(`RESOLUTION_LADDER.md` §1.1·§4, 원칙 4·8). 세그먼트
    위상에서 `_link_targets`로 `(line, segment, station_no, direction) -> to_station_no`
    대응표를 한 번 만들고, 그 표를 슬롯 표에 **이너 조인**한다 — 이 한 번의 조인이 세 가지를
    동시에 한다: (a) 실제 링크마다 `to_station_no`를 붙이고, (b) 대응이 없는 경계 셀(종점·절단면·
    분기점)을 별도 처리 없이 행 자체를 만들지 않아 걸러내고, (c) 강동처럼 한 역이 세그먼트
    여러 개에 걸치는 경우도 세그먼트마다 대응표에서 독립적으로 조회되므로 세그먼트 수만큼
    (서로 다른 `to_station_no`를 가진) 별개 행으로 자연히 갈라져 모호성 플래그 없이 중복 키
    문제가 풀린다(열차 표 239가 `link_ambiguous`로 표시해야 했던 것과 다르다 — 여기는 슬롯
    집계 표라 지선들이 동시에 유효한 값이기 때문이다).

    `predictor_version`은 `full_table`에 없는 컬럼이라(호출자 `run()`이 `meta["predictor_version"]`을
    스칼라로 넘긴다) 행 단위 컬럼으로 붙인다 — BE가 이 컬럼을 행 단위로 요청했다
    (`FROME_BE-crowd-pred-load-path.md` 1.2절). **9호선 2·3단계 행만 예외로
    `LINE9_PREDICTOR_VERSION`을 쓴다** — 그 행은 모델을 타지 않으므로(`pred_source ==
    LINE9_PRED_SOURCE`) 모델 아티팩트 이름을 그대로 흘리면 BE에 잘못된 출처를 알려주게 된다.

    반환: `(link_tbl, stats)`. `stats`는 `link_rows`(출력 행 수), `boundary_dropped_keys`(대응표에
    타깃이 없어 걸러진 `(line, segment, station_no, direction)` 키 조합 수 — 슬롯 수가 아니라
    **키** 단위로 센다, 슬롯마다 같은 경계가 반복되므로 행 수를 그대로 쓰면 슬롯 수만큼 부풀려진다),
    `distinct_links`(날짜와 무관하게 존재하는 고유 물리 링크 수).
    """
    targets = _link_targets(segments)
    key_cols = ["line", "segment", "station_no", "direction"]
    merged = full_table.merge(targets, on=key_cols, how="inner")
    merged = merged.rename(columns={"station_no": "from_station_no"})
    merged["predictor_version"] = np.where(
        merged["pred_source"].to_numpy() == LINE9_PRED_SOURCE,
        LINE9_PREDICTOR_VERSION,
        predictor_version,
    )
    link_tbl = (
        merged.reindex(columns=LINK_OUTPUT_COLS)
        .sort_values(["line", "from_station_no", "direction", "time_slot_30min"], kind="mergesort")
        .reset_index(drop=True)
    )

    dropped_keys = (
        full_table[key_cols]
        .drop_duplicates()
        .merge(targets[key_cols].drop_duplicates(), how="left", indicator=True)
    )
    stats = {
        "link_rows": len(link_tbl),
        "boundary_dropped_keys": int((dropped_keys["_merge"] == "left_only").sum()),
        "distinct_links": len(
            merged[["line", "from_station_no", "to_station_no", "direction"]].drop_duplicates()
        ),
    }
    return link_tbl, stats


def _slot30_to_index(slot30: str) -> int:
    """`"HH:MM"` 30분 슬롯 문자열 → BE가 쓰는 0~47 인덱스(244).

    `index = HH*2 + (MM == 30 ? 1 : 0)`을 직접 계산한다 — `disaggregate.slot30_start_minutes`를
    재사용하지 않는다. 그 함수는 `hh < 4`인 슬롯에 1440분을 더해 운행일(다음날 새벽) 기준으로
    정렬하는 용도라 `00:00`/`00:30`이 48/49가 되어 여기서 BE가 기대하는 0/1과 어긋난다
    (`TO_BE-crowd-contract-answers.md` 1.3절, `FROME_BE-crowd-pred-load-path.md` 6.1절).
    """
    hh, mm = int(slot30[:2]), int(slot30[3:5])
    return hh * 2 + (1 if mm == 30 else 0)


def write_link_csv(link_table: pd.DataFrame, path: Path) -> int:
    """링크 표 → BE 적재용 CSV(244). BE가 확정한 헤더 순서 그대로 쓴다.

    (`FROME_BE-crowd-pred-load-path.md` 6.1절: `pred_date, line, from_station_no, to_station_no,
    direction, time_slot, level, data_status, pred_source, predictor_version`). `date`는
    `YYYY-MM-DD` 문자열(`pred_date`)로, `time_slot_30min`은 `_slot30_to_index`로 0~47 정수
    (`time_slot`)로, `congestion_pct`는 `level`로 이름만 바뀐다 — 값 자체(NaN 포함)는 그대로다.
    NaN인 `level`은 `to_csv` 기본 동작대로 빈 칸으로 쓰인다(BE가 요청한 표현, 6.1절).
    `_atomic_write`로 원자적으로 쓰고 실제로 쓴 행 수를 돌려준다 — 이 값이 `.meta.json`의
    `link_csv_rows`(BE 6.2절 "산출 행 수" 요청)로 그대로 들어간다.
    """
    frame = pd.DataFrame(
        {
            "pred_date": link_table["date"].dt.strftime("%Y-%m-%d"),
            "line": link_table["line"],
            "from_station_no": link_table["from_station_no"],
            "to_station_no": link_table["to_station_no"],
            "direction": link_table["direction"],
            "time_slot": link_table["time_slot_30min"].map(_slot30_to_index),
            "level": link_table["congestion_pct"],
            "data_status": link_table["data_status"],
            "pred_source": link_table["pred_source"],
            "predictor_version": link_table["predictor_version"],
        }
    )
    _atomic_write(lambda p: frame.to_csv(p, index=False, encoding="utf-8"), path)
    return len(frame)


def link_csv_path(out_dir: Path, target_date: pd.Timestamp, generated_at: datetime) -> Path:
    """BE 적재용 CSV 경로 — **`link_` 토큰이 없다.**

    parquet(`predictions_link_{date}.parquet`)과 달리 이 이름에는 `link_`가 빠진다. 취향이 아니라
    BE가 확정한 이름이다(`FROME_BE-crowd-pred-load-path.md` 6.3절 제안 → 이번 통지에서 재확인) —
    BE의 fetch glob이 `predictions_*.csv`이고 파일명에서 날짜를 뽑아 쓴다. `_HHMMSS`는 같은 날짜를
    다시 만들어도 파일명이 겹치지 않게 하려는 것이고, 그 값은 `generated_at`과 같은 순간이라
    사이드카 meta(`write_link_csv_sidecar_meta`)·3절 meta의 `generated_at`과 일치한다.

    규칙을 여기 한 곳에 모아 둔 이유는 `SERVING_CONTRACT.md` 8.1절이 BE 계약이고, 이름이 조용히
    바뀌면 BE 로더가 파일을 못 찾거나 날짜 파싱이 깨지기 때문이다 — 테스트가 이 함수를 대조한다.
    """
    return out_dir / f"predictions_{target_date:%Y-%m-%d}_{generated_at:%H%M%S}.csv"


def write_link_csv_sidecar_meta(
    csv_path: Path, target_date: pd.Timestamp, row_count: int, generated_at: datetime
) -> None:
    """BE CSV(`write_link_csv`)와 짝이 되는 사이드카 meta — CSV와 같은 basename의 `.meta.json`.

    날짜당 하나뿐인 풍부한 `.meta.json`(`validated_meta`, 3절)은 CSV가 `_HHMMSS`로 여러 개
    쌓여도 재생성할 때마다 덮어써진다 — 그러면 이전 CSV는 짝 meta를 잃고, 남은 meta의
    `link_csv_rows`는 새 CSV 것이 된다. BE의 행 수 대조(전송 손상 검증, 6.2절)가 바로 이 상황을
    잡으려는 장치인데 그 구조로는 못 잡는다. 이 사이드카는 CSV 하나마다 독립적으로 남아 그 문제를
    막는다 — 키는 3개만, `row_count`는 BE가 요청한 이름 그대로다.
    """
    payload = {
        "target_date": pd.Timestamp(target_date).strftime("%Y-%m-%d"),
        "row_count": row_count,
        "generated_at": generated_at.isoformat(timespec="seconds"),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    _atomic_write(
        lambda p, text=text: p.write_text(text, encoding="utf-8"),
        csv_path.with_suffix(".meta.json"),
    )


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
    link_table: bool | None = None,
    line9: bool | None = None,
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

    # 9호선 2·3단계 — lookup 기준선 전용(위 모듈 docstring "9호선 2·3단계" 절). 기본 켜짐(설정값)
    # — CLI(`--line9`/`--no-line9`)가 명시하면 그것을 따른다. `line9_panel`은 모델 패널(`panel`)과
    # 절대 합치지 않는다 — station_no가 학습 패널에 0건이라 모델에 들어가면 미학습 범주가 된다.
    use_line9 = settings.crowd_line9_serving if line9 is None else line9
    line9_panel = load_line9_panel() if use_line9 else None
    line9_lookup = DayTypeLookupBaseline().fit(line9_panel) if line9_panel is not None else None

    # `resolved_segments`는 station_no 집합만 본다 — 9호선 역번호를 이 집합에 넣으면(모델 패널
    # 자체는 안 건드린다) `line_topology.yaml`의 "9호선 2·3단계" 세그먼트가 자동으로 채워져
    # 재귀식(`_congestion_table_full`)·링크 표(`to_link_table`) 양쪽에 그대로 편입된다. 9호선
    # station_no는 어차피 패널(`panel`)의 model 입력에는 없으므로(아래 predict_day 호출은 여전히
    # `panel`만 쓴다) 인접역·환승 피처(`adjacency.build_transfer_map`)는 실제 데이터가 있는 행에만
    # 조인돼 기존 1~8호선 모델 결과에는 영향이 없다.
    station_source = (
        panel
        if line9_panel is None
        else pd.concat([panel[["station_no"]], line9_panel[["station_no"]]], ignore_index=True)
    )
    segments, gaps = resolved_segments(station_source)
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

    # 244: 링크(from/to) 표도 기본 꺼짐(설정값) — CLI(`--link-table`/`--no-link-table`)가
    # 명시하면 그것을 따른다.
    use_links = settings.crowd_link_table if link_table is None else link_table

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
        if line9_panel is not None:
            predicted_line9 = predict_line9_day(line9_panel, line9_lookup, d, holidays)
            predicted_all = pd.concat([predicted, predicted_line9], ignore_index=True, sort=False)
        else:
            predicted_all = predicted
        full = _congestion_table_full(predicted_all, segments, capacity, calibration, thresholds)
        table = full.reindex(columns=OUTPUT_COLS)
        line9_rows = int((table["line"] == "9호선").sum())
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

        # 244: CSV 파일명 타임스탬프와 meta.generated_at이 같은 순간을 가리켜야 한다(BE가
        # `meta.generated_at`으로 재적재를 판정하므로, 두 값이 다르면 판정이 어긋난다).
        now = datetime.now(UTC).astimezone()

        link_meta = {"link_table": bool(use_links), "link_csv_rows": None}
        if use_links:
            link_tbl, lstats = to_link_table(full, segments, meta["predictor_version"])
            link_path = out_dir / f"predictions_link_{d:%Y-%m-%d}.parquet"
            _atomic_write(
                lambda p, link_tbl=link_tbl: link_tbl.to_parquet(p, index=False), link_path
            )
            csv_path = link_csv_path(out_dir, d, now)
            csv_rows = write_link_csv(link_tbl, csv_path)
            link_meta["link_csv_rows"] = csv_rows
            write_link_csv_sidecar_meta(csv_path, d, csv_rows, now)
            print(
                f"[배치] {d:%Y-%m-%d} → {csv_path.name} ({lstats['link_rows']:,}행, "
                f"boundary_dropped_keys {lstats['boundary_dropped_keys']}, "
                f"distinct_links {lstats['distinct_links']})",
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
                **link_meta,
                "line9_included": bool(use_line9),
                "line9_rows": line9_rows,
                "generated_at": now.isoformat(timespec="seconds"),
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
    ap.add_argument(
        "--link-table",
        dest="link_table",
        action="store_true",
        default=None,
        help=(
            "링크(from/to) 표(predictions_link_*.parquet + BE CSV)도 산출한다"
            "(기본: settings.crowd_link_table)"
        ),
    )
    ap.add_argument(
        "--no-link-table",
        dest="link_table",
        action="store_false",
        help="링크(from/to) 표를 산출하지 않는다(설정값이 켜져 있어도 이번 실행만 끈다)",
    )
    ap.add_argument(
        "--line9",
        dest="line9",
        action="store_true",
        default=None,
        help=(
            "9호선 2·3단계 13역을 lookup 기준선으로 편입한다(모델에는 넣지 않는다, "
            "기본: settings.crowd_line9_serving)"
        ),
    )
    ap.add_argument(
        "--no-line9",
        dest="line9",
        action="store_false",
        help="9호선 편입을 끈다(설정값이 켜져 있어도 이번 실행만 끈다)",
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
        link_table=args.link_table,
        line9=args.line9,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
