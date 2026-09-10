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

## 알려진 잔여 결측 — 2호선 지선의 방향 라벨 스킴이 다르다

스냅샷은 2호선을 본선·지선 구분 없이 54역 전부 **내선/외선**으로만 보고한다(2026-09-10
대조 확인). 그런데 `line_topology.yaml`의 성수지선·신정지선은 `circular` 플래그가 없어
`build_congestion_label.py`가 상선/하선으로 계산한다 — 그 결과 지선 역(용답·신답·신설동·
도림천·양천구청·신정네거리 등) 3,393행이 매칭 실패로 남는다. 이건 수치 오류가 아니라
**방향 라벨 체계 자체가 다른 것**이라 여기서 임의로 맞추지 않는다(원칙 1) — 지선을
순환선으로 취급할지 여부는 `line_topology.yaml`/`build_congestion_label.py` 쪽에서
따로 판단할 문제라 이 모듈의 스코프 밖에 남겨 둔다.

## 9호선 스냅샷엔 역번호가 없다

XLSX 원본(9호선 혼잡도 자료)에 역명만 있고 역번호 컬럼이 없어 파싱 결과의 `station_no`가
전부 결측이다(48,816/48,816). `parsers_crowd_line9_daily_ridership.load_station_master()`
의 역명(마스터 정본, "올림픽공원(한국체대)")과 스냅샷 표기("올림픽공원")가 하나 다르다 —
별칭으로 붙인다. 1단계(개화~신논현) 역명은 이번 스코프 밖이라 매핑에서 걸러진다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.build_congestion_calibration
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from DATA_ENGINE.eda.build_crowd_panel import attach_calendar
from DATA_ENGINE.eda.parsers_crowd_line9_daily_ridership import load_station_master

AI_ROOT = Path(__file__).resolve().parents[2]
CROWD_INTERIM = AI_ROOT / "data" / "CROWD" / "interim"
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"

LABEL_NAME = "crowd_congestion_label_2024_2026.parquet"
SNAPSHOT_NAME = "crowd_congestion_long.parquet"
OUTPUT_NAME = "crowd_congestion_calibration.parquet"

# 9호선 스냅샷의 day_type 정의를 그대로 따른다 — 주말+공휴일을 "휴일" 하나로 묶는다.
_LINE9_DAY_TYPE_BUCKET = {"평일": "평일", "토요일": "휴일", "일요일": "휴일", "휴일": "휴일"}

# 2호선 성수지선·신정지선 역 — line_topology.yaml 참고. 스냅샷은 이 역들도 본선과 같이
# 내선/외선으로 보고하는데 재귀식은 상선/하선으로 계산해(지선이 circular 세그먼트가
# 아니라서) 방향 라벨이 안 맞는다 — 잔여 매칭 실패를 진단할 때 구분하는 용도로만 쓴다.
_LINE2_BRANCH_STATIONS = {211, 244, 245, 250, 246, 234, 247, 248, 249}

_SLOT_PATTERN = re.compile(r"^(\d{2}):(\d{2})$")


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


def raw_hourly_mean(labels: pd.DataFrame) -> pd.DataFrame:
    """(station_no, direction, line, day_type_bucket, time_slot) 별 raw 평균과 표본 날짜 수.

    `crowd_congestion_label_2024_2026.parquet`에는 `day_type`이 없다 — 승하차 패널과
    달리 재귀식 결과는 (date, station_no, ...) 원자 단위라 요일유형을 안 들고 있어서,
    `build_crowd_panel.attach_calendar`로 `date`에서 다시 파생한다.
    """
    frame = attach_calendar(labels.copy())
    frame["day_type_bucket"] = bucket_day_type(frame["line"], frame["day_type"])
    frame = frame.dropna(subset=["day_type_bucket"])

    grouped = frame.groupby(
        ["station_no", "direction", "line", "day_type_bucket", "time_slot"], observed=True
    )
    return grouped["congestion_raw_pct"].agg(raw_mean="mean", n_dates="count").reset_index()


def build_calibration_ratio() -> tuple[pd.DataFrame, dict[str, int]]:
    labels = pd.read_parquet(CROWD_PROCESSED / LABEL_NAME)
    snapshot = pd.read_parquet(CROWD_INTERIM / SNAPSHOT_NAME)

    snapshot = attach_snapshot_station_no(snapshot)
    snapshot = snapshot.copy()
    snapshot["hour_bucket"] = snapshot["time_slot"].map(slot_30min_to_hour_bucket)

    raw_mean = raw_hourly_mean(labels)

    merged = snapshot.merge(
        raw_mean,
        left_on=["station_no", "direction", "line", "day_type", "hour_bucket"],
        right_on=["station_no", "direction", "line", "day_type_bucket", "time_slot"],
        how="left",
        suffixes=("", "_raw"),
    )
    merged["ratio"] = merged["congestion_pct"] / merged["raw_mean"]
    # raw_mean이 0이면 나눗셈이 inf가 된다 — 0으로 나눈 결과는 배율이 아니라 결측이다.
    merged.loc[merged["raw_mean"] == 0, "ratio"] = pd.NA

    diagnostics = {
        "스냅샷_행": len(snapshot),
        "raw_평균_매칭_실패": int(merged["raw_mean"].isna().sum()),
        "배율_계산됨": int(merged["ratio"].notna().sum()),
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
    return merged[cols], diagnostics


def save_calibration(ratio: pd.DataFrame) -> Path:
    CROWD_PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = CROWD_PROCESSED / OUTPUT_NAME
    ratio.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    ratio, diagnostics = build_calibration_ratio()
    out_path = save_calibration(ratio)

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
        print(f"  raw 평균이 0이라 배율을 정의할 수 없어 제외한 행: {len(zero_raw):,}행")
    print("\n[배율 분포] 호선별 요약:")
    print(
        ratio.dropna(subset=["ratio"])
        .groupby("line", observed=True)["ratio"]
        .describe()[["count", "mean", "50%", "min", "max"]]
        .round(2)
        .to_string()
    )
    print(f"\n저장 완료: {out_path} ({len(ratio):,}행)")


if __name__ == "__main__":
    main()
