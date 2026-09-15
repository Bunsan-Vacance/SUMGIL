"""재귀식 혼잡도(`congestion_raw_pct`)와 실측 스냅샷(`congestion_pct`)을 대조해
역·방향·요일유형·30분 단위 보정 배율표를 만든다 → `crowd_congestion_calibration.parquet`.

## 이 배율표가 두 문제를 동시에 푼다

`build_congestion_label.py`가 이미 적어둔 다음 단계다. `congestion_raw_pct`는 배차
미보정이라 실측보다 9~10배 과대하고(1시간 승하차를 그대로 나눈 값), 시간 해상도도
1시간(20슬롯)뿐이라 실측(30분, 39슬롯)보다 성기다. 배율을

    배율(역, 방향, 요일유형, 30분) = 실측_30분 ÷ mean_날짜(raw_1시간)

로 30분 단위에 정의하면, 스케일(배차 보정)과 모양(30분 분해)이 **한 번에** 맞는다 — 그
30분이 속한 1시간의 raw 평균과 실측 30분값의 비율이므로, 같은 1시간 안에서도 전반·후반
30분의 배율이 갈려 자연히 분해가 된다.

## 요일유형 — 두 원천이 쓰는 체계가 서로 다르다

실측 스냅샷의 `day_type`은 **호선마다 다르다**:
    - 1~8호선: 평일 / 토요일 / 일요일 (3종, "휴일" 구분 없음)
    - 9호선: 평일 / 휴일 (2종, 주말+공휴일을 전부 "휴일" 하나로 묶음)

반면 재귀식 라벨의 `day_type`(`build_crowd_panel.py`의 `attach_calendar`)은 달력 기준
4종(평일/토요일/일요일/휴일 — 공휴일이면 요일과 무관하게 "휴일"로 덮어씀)이다.

**1~8호선의 "휴일"(공휴일)은 대응하는 스냅샷 구간이 없다** — 평일·토요일·일요일 중 어느
쪽과도 같다고 볼 근거가 없어(원칙 1) 배율 계산에서 제외하고 결측으로 남긴다. 9호선은
스냅샷 자체가 "휴일"을 주말+공휴일 통합으로 정의하므로, 재귀식 쪽 토요일·일요일·휴일을
전부 "휴일" 하나로 묶어 맞춘다 — 이건 추정이 아니라 원천이 스스로 쓰는 정의를 그대로
따르는 것이다.

## 199 — 변형(`CalibrationVariant`)으로 적합 규칙을 고른다

88이 "이 모듈의 스코프 밖"으로 남겼던 두 결측 원인을 199가 여기서 푼다. 규칙을 상수로 박지 않고
`CalibrationVariant`로 받아, `validation/CROWD/calibration-refit/`가 **같은 심판(홀드아웃·등급
일치율·`data_status`)으로 후보를 재고** 채택안을 기본값으로 둔다. 현행(88) 재현은
`CalibrationVariant.current()`다 — 바이트 단위로 같은 표가 나온다.

- **2호선 지선 방향 대응(`branch_direction_map`).** 스냅샷은 2호선 54역 전부를 **내/외선**으로
  보고하는데(2026-09-10 대조 확인) `line_topology.yaml`의 성수·신정지선은 `circular`가 아니라
  재귀식이 **상/하선**으로 계산한다 → 조인 공집합. 146이 두 지선의 대응이 서로 반대임을 실측
  출퇴근 비대칭·상관으로 확정해 `congestion.BRANCH_DIRECTION_MAP`에 고정했다. 그 대응표를 여기
  조인 직전에 적용한다(라벨 파일은 건드리지 않는다).
- **절단면 경계 유입(`boundary_inflow`).** `truncated: true` 구간은 절단면 바깥에서 들어와
  구간을 통과하는 승객이 있는데 재귀식은 닫힌 OD를 가정해 그 승객을 못 본다 — 진행방향 끝
  링크의 재차가 정의상 0이 되어 배율이 산출조차 안 된다. 146 §4-C가 `meas ≈ s·raw + c` 적합에서
  상수항이 정원의 20~30%로 실재함을 확인했다. 여기서는 그 상수를 **정원 % 단위(`c/s`)로 환산해
  raw에 더한 뒤 배율을 다시 적합**하고, 더한 양을 `raw_offset` 컬럼으로 표에 같이 싣는다.
  서빙(`congestion.apply_calibration`)은 `(raw + raw_offset) × ratio`를 계산하므로 오프셋 0인
  표에서는 기존과 완전히 같다. 146 §4-D의 (a)가 실패한 이유(기존 배율표 위에 상수를 더한 이중
  계상)는 여기서 생기지 않는다 — 상수를 넣은 raw로 배율을 **다시** 적합하기 때문이다.
- **적합 창(`fit_window`).** 스냅샷 기준일과 승하차 평균 창의 어긋남(142 §2-B·§6)을 고르는 축이다.

진짜 종점(6호선 응암 순환 시작, 5호선 지선 종점 등)은 재차 0이 **정답**이라 대상이 아니다 —
`truncated` 플래그가 붙은 구간만 본다.

## 9호선 스냅샷은 (station, direction, day_type, time_slot) 키가 원래 중복이다

1~8호선 스냅샷은 "대표 1주" 단일 조사라 이 키가 유일하다. 9호선은 **2020~2025년 6개
연도**를 각각 따로 담고 있고, **급행/일반**도 별도 행이라 키 하나에 최대 12행이 붙는다.
아무 처리 없이 조인하면 그 행 수만큼 배율이 카티전 곱으로 불어난다(2026-09-10 발견 —
8번 작업 중 항등식 검증에서 드러남).

- **연도는 2025년만 쓴다.** 종합운동장 출근시간대 혼잡도가 2020년 30.8%→2025년 63.8%로
  코로나 이후 뚜렷한 회복 추세다(직접 대조 확인) — 다년 평균을 내면 우리 목표 구간
  (2025~2026)의 실제 수준을 과소평가한다. 2025년 단독으로 13역·평일/휴일·급행/일반이
  전부 커버돼 다른 연도가 없어도 결측이 생기지 않는다.
- **일반/급행을 별도 배율표로 낸다.** 우리 재귀식 라벨은 급행/일반을 구분하지 않고
  계산한 총 승하차 기반이라, 두 배율 다 **같은 raw 평균을 분모로** 쓰되 분자(실측)만
  일반/급행으로 갈라 계산한다 — "raw가 실제로 몇 배인가"를 보는 두 개의 독립된 렌즈다.
  13역 중 6역(선정릉·봉은사·종합운동장·석촌·올림픽공원·중앙보훈병원)에만 급행이 서므로
  급행 배율표는 이 6역만 담는다. `main()`이 두 표를 각각
  `crowd_congestion_calibration.parquet`(일반)·`crowd_congestion_calibration_express.parquet`
  (급행)로 저장한다.

## 9호선 스냅샷엔 역번호가 없다

XLSX 원본(9호선 혼잡도 자료)에 역명만 있고 역번호 컬럼이 없어 파싱 결과의 `station_no`가
전부 결측이다(48,816/48,816). `parsers_crowd_line9_daily_ridership.load_station_master()`
의 역명(마스터 정본, "올림픽공원(한국체대)")과 스냅샷 표기("올림픽공원")가 하나 다르다 —
별칭으로 붙인다. 1단계(개화~신논현) 역명은 이번 스코프 밖이라 매핑에서 걸러진다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.build_congestion_calibration            # 채택 변형(기본값)
    python -m DATA_ENGINE.eda.build_congestion_calibration --variant current   # 88 현행 재현
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.CROWD.pipeline.congestion import bucket_direction
from DATA_ENGINE.eda.boundary_inflow import boundary_offsets
from DATA_ENGINE.eda.build_crowd_panel import attach_calendar
from DATA_ENGINE.eda.parsers_crowd_line9_daily_ridership import load_station_master

AI_ROOT = Path(__file__).resolve().parents[2]
CROWD_INTERIM = AI_ROOT / "data" / "CROWD" / "interim"
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"

LABEL_NAME = "crowd_congestion_label_2024_2026.parquet"
SNAPSHOT_NAME = "crowd_congestion_long.parquet"
OUTPUT_NAME = "crowd_congestion_calibration.parquet"
OUTPUT_NAME_EXPRESS = "crowd_congestion_calibration_express.parquet"
ARCHIVE_DIR = CROWD_PROCESSED / "_archive"

# 배율표가 선 실측 스냅샷의 기준일(142 1절에서 2025-11-30판과 완전 일치함을 확인).
SNAPSHOT_RELEASE = "2025-11-30"

# 9호선 스냅샷의 day_type 정의를 그대로 따른다 — 주말+공휴일을 "휴일" 하나로 묶는다.
_LINE9_DAY_TYPE_BUCKET = {"평일": "평일", "토요일": "휴일", "일요일": "휴일", "휴일": "휴일"}

# 2호선 성수지선·신정지선 역 — line_topology.yaml 참고. 스냅샷은 이 역들도 본선과 같이
# 내선/외선으로 보고하는데 재귀식은 상선/하선으로 계산해(지선이 circular 세그먼트가
# 아니라서) 방향 라벨이 안 맞는다 — 잔여 매칭 실패를 진단할 때 구분하는 용도로만 쓴다.
_LINE2_BRANCH_STATIONS = {211, 244, 245, 250, 246, 234, 247, 248, 249}

# 9호선 스냅샷 다년치 중 이 연도만 쓴다 — 모듈 docstring "9호선 스냅샷은 키가 원래
# 중복이다" 참고(코로나 회복 추세를 피하기 위해 최신 연도만).
_LINE9_CALIBRATION_YEAR = 2025

_SLOT_PATTERN = re.compile(r"^(\d{2}):(\d{2})$")


@dataclass(frozen=True)
class CalibrationVariant:
    """배율 적합 규칙의 축 세 개(199). 후보 비교와 재생성이 같은 코드를 쓰게 하는 장치다.

    - `branch_direction_map` — 2호선 지선의 상/하선을 스냅샷의 내/외선으로 옮기고 조인한다(A1).
    - `boundary_inflow` / `boundary_scale` — 절단 구간에 경계 유입 상수를 주입한 raw로 재적합한다(B1).
      `boundary_scale=0.0`이면 상수가 전부 0이라 **주입하지 않은 표와 바이트 단위로 같다**(테스트로 고정).
    - `fit_window` — raw 평균을 낼 승하차 날짜 창. `all`(현행) / `snapshot_year`(스냅샷 기준일의
      연도만) / `snapshot_season`(기준일 ±`window_weeks`주).
    """

    branch_direction_map: bool = True
    boundary_inflow: bool = True
    boundary_method: str = "anchored"
    boundary_apply: str = "segment"
    boundary_scale: float = 1.0
    fit_window: str = "all"
    snapshot_release: str = SNAPSHOT_RELEASE
    window_weeks: int = 13

    @classmethod
    def current(cls) -> CalibrationVariant:
        """88이 만든 현행 표를 그대로 재현하는 설정 — 모든 비교의 기준선."""
        return cls(branch_direction_map=False, boundary_inflow=False, fit_window="all")

    @property
    def code(self) -> str:
        parts = [
            "branch" if self.branch_direction_map else "nobranch",
            (
                f"{self.boundary_method}-{self.boundary_apply}{self.boundary_scale:g}"
                if self.boundary_inflow
                else "noinflow"
            ),
            self.fit_window,
        ]
        return "_".join(parts)


def fit_window_mask(dates: pd.Series, variant: CalibrationVariant) -> pd.Series:
    """적합 창 — raw 평균에 넣을 승하차 날짜를 고른다.

    `snapshot_season`은 스냅샷 기준일 ±`window_weeks`주다. 기준일 주변만 남기면 계절이 맞는 대신
    셀당 표본이 줄어 분산이 커진다 — 어느 쪽이 나은지는 홀드아웃이 판정한다(142 §6 미해결).
    """
    if variant.fit_window == "all":
        return pd.Series(True, index=dates.index)
    ref = pd.Timestamp(variant.snapshot_release)
    if variant.fit_window == "snapshot_year":
        return dates.dt.year == ref.year
    if variant.fit_window == "snapshot_season":
        span = pd.Timedelta(weeks=variant.window_weeks)
        return (dates >= ref - span) & (dates <= ref + span)
    raise ValueError(f"알 수 없는 적합 창: {variant.fit_window!r}")


def attach_boundary_offset(
    merged: pd.DataFrame, labels: pd.DataFrame, variant: CalibrationVariant
) -> pd.DataFrame:
    """`merged`에 `raw_offset`을 붙인다 — 절단 구간만 값이 있고 나머지는 0이다(199 B).

    상수 적합은 `DATA_ENGINE/eda/boundary_inflow.py`에 있고, 연도 홀드아웃 하네스도 같은 함수를
    쓴다. 끄면(`boundary_inflow=False`) 전 셀 0이라 88 현행 표와 수치가 같다.
    """
    out = merged.copy()
    if not variant.boundary_inflow:
        out["raw_offset"] = 0.0
        return out
    cell_key = ["station_no", "direction", "day_type", "time_slot"]
    offsets = boundary_offsets(
        out,
        available=set(labels["station_no"].astype("int64").unique()),
        method=variant.boundary_method,
        apply_to=variant.boundary_apply,
        scale=variant.boundary_scale,
    )
    return out.merge(offsets, on=cell_key, how="left").assign(
        raw_offset=lambda f: f["raw_offset"].fillna(0.0)
    )


def dedupe_snapshot_keys(snapshot: pd.DataFrame, line9_train_type: str = "일반") -> pd.DataFrame:
    """9호선 스냅샷의 (연도·급행/일반) 중복을 걷어내 키 하나당 한 행으로 만든다.

    1~8호선은 연도·train_type 축이 아예 없어(단일 대표 조사) 이 필터가 영향을 주지
    않는다. 9호선만 `year == 2025` & `train_type == line9_train_type`으로 좁힌다 —
    `"일반"`(기본값)이면 13역, `"급행"`이면 급행이 서는 6역만 남는다(급행이 없는 역은
    애초에 그 값을 가진 행이 없어 자연히 빠진다).
    """
    is_line9 = snapshot["line"] == "9호선"
    keep = ~is_line9 | (
        (snapshot["year"] == _LINE9_CALIBRATION_YEAR) & (snapshot["train_type"] == line9_train_type)
    )
    return snapshot[keep].reset_index(drop=True)


def slot_30min_to_hour_bucket(slot: str) -> str:
    """실측 스냅샷의 30분 라벨(`"HH:MM"`)을 재귀식 라벨의 20슬롯 라벨로 바꾼다.

    `build_crowd_panel.py`가 쓰는 운행일 규칙과 같다 — 00:00·00:30(자정 이후)은 `24~`,
    05:30(첫차 준비)은 `~06`, 나머지는 그 시(hour)의 `HH-HH+1` 버킷이다.
    """
    m = _SLOT_PATTERN.match(slot)
    if not m:
        raise ValueError(f"알 수 없는 시간대 형식: {slot!r}")
    hour = int(m.group(1))
    if hour == 0:
        return "24~"
    if hour == 5:
        return "~06"
    return f"{hour:02d}-{hour + 1:02d}"


def line9_station_no_by_name() -> dict[str, int]:
    """스냅샷의 9호선 역명(원본 표기)을 station_no로 매핑한다.

    `load_station_master()`는 마스터 정본 이름("올림픽공원(한국체대)")을 쓰는데, 스냅샷은
    승하차 원본과 같은 표기("올림픽공원")라 그 한 건만 별칭으로 바꿔 준다.
    """
    master = load_station_master()
    mapping = dict(zip(master["station_name_master"], master["station_no"]))
    mapping["올림픽공원"] = mapping.pop("올림픽공원(한국체대)")
    return mapping


def attach_snapshot_station_no(snapshot: pd.DataFrame) -> pd.DataFrame:
    """9호선 행에 역명 기준으로 station_no를 붙이고, 이번 스코프(2·3단계 13역) 밖은 뺀다.

    1~8호선은 원본에 이미 station_no가 있어 그대로 둔다. 9호선 1단계 역명(예: "여의도",
    "노량진")은 매핑에 없으니 자동으로 걸러진다 — 조용히 사라지는 게 아니라 이번
    스코프(2·3단계만 편입) 자체가 그렇게 정의돼 있다.
    """
    out = snapshot.copy()
    is_line9 = out["line"] == "9호선"
    name_to_no = line9_station_no_by_name()
    out.loc[is_line9, "station_no"] = out.loc[is_line9, "station_name"].map(name_to_no)
    # 1~8호선의 기존 station_no(float일 수 있음)와 dtype을 맞춘다.
    return out.dropna(subset=["station_no"]).astype({"station_no": "int64"})


def bucket_day_type(line: pd.Series, day_type: pd.Series) -> pd.Series:
    """재귀식 라벨의 4종 day_type을 호선별 스냅샷 체계로 접는다.

    9호선은 토요일·일요일·휴일을 전부 "휴일"로 묶고(스냅샷 정의 그대로), 1~8호선은
    "휴일"(공휴일)에 대응하는 스냅샷 구간이 없어 None으로 둬 이후 조인에서 빠지게 한다.
    """
    is_line9 = line == "9호선"
    bucketed = day_type.where(~is_line9, day_type.map(_LINE9_DAY_TYPE_BUCKET))
    bucketed = bucketed.where(is_line9 | (day_type != "휴일"), None)
    return bucketed


def raw_hourly_mean(
    labels: pd.DataFrame, variant: CalibrationVariant | None = None
) -> pd.DataFrame:
    """(station_no, direction, line, day_type_bucket, time_slot) 별 raw 평균과 표본 날짜 수.

    `crowd_congestion_label_2024_2026.parquet`에는 `day_type`이 없다 — 승하차 패널과
    달리 재귀식 결과는 (date, station_no, ...) 원자 단위라 요일유형을 안 들고 있어서,
    `build_crowd_panel.attach_calendar`로 `date`에서 다시 파생한다.

    `variant.branch_direction_map`이 켜지면 2호선 지선의 상/하선을 **조인 직전에** 내/외선으로
    옮긴다(146 대응표). 라벨 파일은 그대로 두고 여기서만 접는 것이라, 88·146이 낸 라벨 수치는
    흔들리지 않는다. `variant.fit_window`는 평균에 넣을 날짜를 좁힌다.
    """
    variant = variant or CalibrationVariant()
    frame = attach_calendar(labels.copy())
    frame = frame[fit_window_mask(frame["date"], variant)]
    frame["day_type_bucket"] = bucket_day_type(frame["line"], frame["day_type"])
    frame = frame.dropna(subset=["day_type_bucket"])
    if variant.branch_direction_map:
        frame["direction"] = bucket_direction(
            frame["segment"] if "segment" in frame.columns else None,
            frame["direction"],
            frame["station_no"],
        )

    grouped = frame.groupby(
        ["station_no", "direction", "line", "day_type_bucket", "time_slot"], observed=True
    )
    return grouped["congestion_raw_pct"].agg(raw_mean="mean", n_dates="count").reset_index()


def build_calibration_ratio(
    line9_train_type: str = "일반",
    variant: CalibrationVariant | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """배율표를 만든다. `line9_train_type`을 `"급행"`으로 주면 급행 6역용 배율표가 된다.

    두 호출 모두 같은 raw 평균(분모, 재귀식은 열차 종류를 구분하지 않는다)을 쓰고
    분자(실측)만 갈라서 계산한다 — "raw가 실제로 몇 배 과대한가"를 일반·급행 두
    시선으로 각각 보는 것이다. 하나가 다른 하나에서 유도되는 관계가 아니다.

    `variant`가 적합 규칙(지선 방향 대응·경계 유입·적합 창)을 정한다 — 모듈 docstring 참고.
    """
    variant = variant or CalibrationVariant()
    labels = pd.read_parquet(CROWD_PROCESSED / LABEL_NAME)
    snapshot = pd.read_parquet(CROWD_INTERIM / SNAPSHOT_NAME)

    snapshot = attach_snapshot_station_no(snapshot)
    snapshot = dedupe_snapshot_keys(snapshot, line9_train_type=line9_train_type)
    snapshot = snapshot.copy()
    snapshot["hour_bucket"] = snapshot["time_slot"].map(slot_30min_to_hour_bucket)

    key = ["station_no", "direction", "line", "day_type", "time_slot"]
    remaining_dupes = snapshot.duplicated(key, keep=False)
    if remaining_dupes.any():
        raise ValueError(
            f"dedupe_snapshot_keys 이후에도 스냅샷 키 중복이 {remaining_dupes.sum()}행 "
            "남아 있다 — 배율표가 조인 시 행 수를 부풀린다. 원인을 먼저 확인할 것."
        )

    raw_mean = raw_hourly_mean(labels, variant)

    merged = snapshot.merge(
        raw_mean,
        left_on=["station_no", "direction", "line", "day_type", "hour_bucket"],
        right_on=["station_no", "direction", "line", "day_type_bucket", "time_slot"],
        how="left",
        suffixes=("", "_raw"),
    )
    merged = attach_boundary_offset(merged, labels, variant)
    fitted_raw = merged["raw_mean"] + merged["raw_offset"]
    merged["ratio"] = merged["congestion_pct"] / fitted_raw
    # 더해 준 뒤에도 0이면 나눗셈이 inf가 된다 — 0으로 나눈 결과는 배율이 아니라 결측이다.
    merged.loc[fitted_raw == 0, "ratio"] = pd.NA

    diagnostics = {
        "스냅샷_행": len(snapshot),
        "raw_평균_매칭_실패": int(merged["raw_mean"].isna().sum()),
        "배율_계산됨": int(merged["ratio"].notna().sum()),
        "경계_유입_주입_셀": int((merged["raw_offset"] > 0).sum()),
    }

    cols = [
        "station_no",
        "station_name",
        "line",
        "direction",
        "day_type",
        "time_slot",
        "congestion_pct",
        "raw_mean",
        "n_dates",
        "ratio",
    ]
    if variant.boundary_inflow:
        cols.append("raw_offset")
    return merged[cols], diagnostics


def save_calibration(ratio: pd.DataFrame, output_name: str = OUTPUT_NAME) -> Path:
    CROWD_PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = CROWD_PROCESSED / output_name
    ratio.to_parquet(out_path, index=False)
    return out_path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def archive_previous(path: Path) -> Path | None:
    """이전 산출물을 `processed/_archive/`로 옮긴다 — 덮어쓰기 전에 되돌릴 수 있게 남긴다.

    `_archive/`는 `data/` 아래라 gitignore 대상이다(용량·재생성 가능). 파일명에 이전 파일의
    수정 시각을 붙여 여러 벌이 겹치지 않게 한다.
    """
    if not path.exists():
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y%m%d-%H%M%S")
    target = ARCHIVE_DIR / f"{path.stem}_{stamp}{path.suffix}"
    path.replace(target)
    return target


def calibration_meta(
    ratio: pd.DataFrame,
    variant: CalibrationVariant,
    diagnostics: dict[str, int],
    previous_sha256: str | None,
    previous_archived: str | None,
) -> dict:
    """`crowd_congestion_calibration.meta.json` 내용 — 이 표가 무엇으로 만들어졌는지(199 규칙 1).

    배율표는 모든 혼잡도 산출의 승수라 모델 아티팩트와 같은 수준으로 추적한다
    (`app/CROWD/pipeline/MODEL_REGISTRY.md` "변환 층 산출물").
    """
    labels_path = CROWD_PROCESSED / LABEL_NAME
    dates = pd.read_parquet(labels_path, columns=["date"])["date"]
    kept = dates[fit_window_mask(dates, variant)]
    return {
        "ticket": "S15P21A104-199",
        "snapshot_release": variant.snapshot_release,
        "snapshot_source": str(CROWD_INTERIM / SNAPSHOT_NAME),
        "label_source": str(labels_path),
        "ridership_window": {
            "mode": variant.fit_window,
            "window_weeks": variant.window_weeks if variant.fit_window else None,
            "start": str(kept.min().date()) if len(kept) else None,
            "end": str(kept.max().date()) if len(kept) else None,
            "n_dates": int(kept.dt.normalize().nunique()),
        },
        "direction_mapping": (
            "congestion.BRANCH_DIRECTION_MAP(146) — 성수지선 하선→외선 / 신정지선 하선→내선, "
            "분기역(211·234) 제외"
            if variant.branch_direction_map
            else "없음(88 현행) — 2호선 지선은 상/하선 그대로라 조인이 공집합"
        ),
        "boundary_variant": (
            f"B1 경계 유입 주입(정원 % 단위, scale={variant.boundary_scale:g}) — "
            "truncated 구간만, 9호선 제외"
            if variant.boundary_inflow
            else "B3 현행 유지 — 경계 셀은 ratio NaN"
        ),
        "variant": asdict(variant),
        "variant_code": variant.code,
        "rows": len(ratio),
        "ratio_defined": int(ratio["ratio"].notna().sum()),
        "ratio_missing": int(ratio["ratio"].isna().sum()),
        "diagnostics": diagnostics,
        "previous_sha256": previous_sha256,
        "previous_archived_as": previous_archived,
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
    }


def _report(label: str, ratio: pd.DataFrame, diagnostics: dict[str, int], out_path: Path) -> None:
    print(f"\n=== {label} ===")
    print(
        f"[안내] 스냅샷 {diagnostics['스냅샷_행']:,}행 중 "
        f"raw 평균 매칭 실패(조인 자체가 안 됨) {diagnostics['raw_평균_매칭_실패']:,}행, "
        f"배율 계산됨 {diagnostics['배율_계산됨']:,}행"
    )
    join_failed = ratio[ratio["raw_mean"].isna()]
    if len(join_failed):
        is_branch = join_failed["station_no"].isin(_LINE2_BRANCH_STATIONS)
        print(
            f"  그중 2호선 지선(성수·신정지선) 방향 라벨 불일치(모듈 docstring 참고): "
            f"{int(is_branch.sum()):,}행"
        )
        print(
            f"  그중 재귀식 라벨 자체에 없는 역(결번·특수 코드, "
            f"build_congestion_label.py의 '설정에는 있으나 승하차 데이터에 없는 역' 참고): "
            f"{int((~is_branch).sum()):,}행"
        )
    zero_raw = ratio[ratio["raw_mean"] == 0]
    if len(zero_raw):
        rescued = int(zero_raw["ratio"].notna().sum())
        print(
            f"  raw 평균이 0인 행: {len(zero_raw):,}행 "
            f"(그중 경계 유입 주입으로 배율이 정의된 행 {rescued:,})"
        )
    if "raw_offset" in ratio.columns:
        injected = ratio[ratio["raw_offset"] > 0]
        print(
            f"  경계 유입 주입 셀 {len(injected):,}행 · 상수 중위 "
            f"{injected['raw_offset'].median():.1f}% 정원"
            if len(injected)
            else "  경계 유입 주입 셀 없음"
        )
    print("[배율 분포] 호선별 요약:")
    print(
        ratio.dropna(subset=["ratio"])
        .groupby("line", observed=True)["ratio"]
        .describe()[["count", "mean", "50%", "min", "max"]]
        .round(2)
        .to_string()
    )
    print(f"저장 완료: {out_path} ({len(ratio):,}행)")


VARIANT_PRESETS: dict[str, CalibrationVariant] = {
    "adopted": CalibrationVariant(),
    "current": CalibrationVariant.current(),
    "branch_only": CalibrationVariant(boundary_inflow=False),
    "branch_year": CalibrationVariant(boundary_inflow=False, fit_window="snapshot_year"),
    "branch_season": CalibrationVariant(boundary_inflow=False, fit_window="snapshot_season"),
}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--variant", default="adopted", choices=sorted(VARIANT_PRESETS))
    ap.add_argument(
        "--boundary-scale",
        type=float,
        default=None,
        help="경계 유입 상수의 배수(0이면 주입하지 않은 표와 같은 수치가 나온다)",
    )
    ap.add_argument("--no-archive", action="store_true", help="이전 산출물을 옮기지 않는다")
    args = ap.parse_args(argv)

    variant = VARIANT_PRESETS[args.variant]
    if args.boundary_scale is not None:
        variant = replace(variant, boundary_scale=args.boundary_scale)

    local_path = CROWD_PROCESSED / OUTPUT_NAME
    previous_sha = sha256_of(local_path) if local_path.exists() else None

    local_ratio, local_diag = build_calibration_ratio(line9_train_type="일반", variant=variant)
    archived = None if args.no_archive else archive_previous(local_path)
    local_path = save_calibration(local_ratio, OUTPUT_NAME)
    meta = calibration_meta(
        local_ratio, variant, local_diag, previous_sha, archived.name if archived else None
    )
    meta["sha256"] = sha256_of(local_path)
    local_path.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    _report(f"일반 · 변형 {variant.code}", local_ratio, local_diag, local_path)
    print(f"메타: {local_path.with_suffix('.meta.json')}")
    if archived:
        print(f"이전 표 보관: {archived}")

    # 급행은 9호선에만 있는 개념이라(1~8호선은 train_type 자체가 없다) dedupe_snapshot_keys가
    # 1~8호선 행을 그대로 통과시켜도, 여기서는 9호선만 남긴다 — "급행" 산출물에 급행이
    # 없는 호선의 행이 섞여 있으면 헷갈린다. 9호선은 199 스코프 밖이라 변형을 적용하지 않는다.
    express_ratio, _ = build_calibration_ratio(
        line9_train_type="급행", variant=CalibrationVariant.current()
    )
    express_ratio = express_ratio[express_ratio["line"] == "9호선"].reset_index(drop=True)
    express_diag = {
        "스냅샷_행": len(express_ratio),
        "raw_평균_매칭_실패": int(express_ratio["raw_mean"].isna().sum()),
        "배율_계산됨": int(express_ratio["ratio"].notna().sum()),
    }
    express_path = save_calibration(express_ratio, OUTPUT_NAME_EXPRESS)
    _report("급행(9호선 6역만)", express_ratio, express_diag, express_path)


if __name__ == "__main__":
    main()
