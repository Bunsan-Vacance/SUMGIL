"""9호선 2·3단계를 `build_crowd_panel.py`와 같은 (date, station_no, time_slot) 격자로
편입한다 → `data/CROWD/processed/crowd_panel_line9_2025_2026.parquet`.

**메인 패널에 직접 합치지 않고 별도 파일로 낸다.** 스키마는 완전히 호환되지만(같은 컬럼,
같은 20슬롯 체계), 날짜 범위가 다르다 — 메인 패널은 2024-01-01~2025-12-31로 고정인데
9호선 원천은 2025-01-01부터라 2024년이 통째로 없고, 2026-01까지 있어 메인 패널의 끝을
넘어간다. 이미 87번 베이스라인 작업이 메인 패널 파일을 그대로 소비하고 있어, 범위가 다른
데이터를 억지로 끼워 넣으면 그 작업의 학습/평가 분할(2024 학습·2025 평가)이 조용히
깨진다. 합치는 시점·방식은 이후 결정 — 지금은 스키마만 맞춰 준비한다.

## 시간대 재배치 — 가장 중요한 변환

9호선 원본은 **달력일** 기준으로 00시~24시를 그대로 쓴다(`parsers_crowd_line9_daily_ridership`
의 24개 슬롯). 반면 메인 패널의 20슬롯 체계(`build_crowd_panel.py`)는 **운행일** 기준이라
자정 이후 이용은 전날 운행일의 `24~` 버킷에 붙는다 — 지하철이 자정 넘어서도 마지막 열차까지
운행하기 때문에 "그날의 운행"으로 취급하는 것이다.

역 하나(예: 언주 하차, 2025-01-01)의 00시대 실측(4명)이 이 재배치가 맞는지 보여준다 —
01~04시는 0에 가깝고(막차 이후 첫차 전까지 운행 공백), 05시대에 다시 늘어난다. 이건 9호선도
1~8호선과 같은 "막차 뒤 서비스 공백 → 첫차 준비" 패턴이라는 뜻이라 아래 재배치가 근거 있다:

- `00-01`~`04-05` (심야 5개 슬롯, 서비스 공백대) → **전날** 날짜의 `24~` 버킷으로 합산 이동
- `05-06` (첫차 준비) → 같은 날 `~06`
- `06-07`~`23-24` → 그대로 (18개, 이름만 유지)

**경계 절단**: 데이터 첫날(2025-01-01)의 00-01~04-05는 2024-12-31의 `24~`가 되는데, 그
전날 몫의 나머지 슬롯(~06 이후)은 원천에 없다. 인위적으로 채우지 않고 그 하루만 `24~` 단독
행으로 둔다 — 결측이 아니라 자연스러운 경계 절단이다.

**질량 보존 검증**: 재배치 전후로 (station_no, direction)별 전체 합계가 같아야 한다 —
합산·재라벨만 하고 값을 만들거나 버리지 않았는지 확인하는 최소한의 체크다(데이터 검증
리포트 원칙 5).

실행:
    cd AI
    python -m DATA_ENGINE.eda.build_crowd_line9_panel
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from DATA_ENGINE.eda.build_crowd_panel import (
    _WEATHER_COLS,
    attach_calendar,
    attach_weather,
    prepare_weather,
)
from DATA_ENGINE.eda.parsers_crowd_line9_daily_ridership import (
    attach_station_master,
    build_line9_daily_long,
    drop_conflicting_duplicates,
)

AI_ROOT = Path(__file__).resolve().parents[2]
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"

OUTPUT_NAME = "crowd_panel_line9_2025_2026.parquet"

# 이 시각(hour) 이하는 전날 "24~" 버킷으로 넘어간다. 04시대(04-05)까지가 서비스 공백대라
# 5(=05시대, "~06")부터는 그날 첫차 준비대로 남긴다.
_LATE_NIGHT_MAX_HOUR = 4


def reshape_to_panel_slots(df: pd.DataFrame) -> pd.DataFrame:
    """9호선의 24개 달력시 슬롯을 메인 패널의 20개 운행일 슬롯으로 재배치한다.

    모듈 docstring의 재배치 규칙을 그대로 구현한다. 입력은 `time_slot`이 `"HH-HH"` 형식인
    long-format(직접 컬럼 이름은 상관없이 date·station_no·time_slot·passengers만 있으면
    된다), 출력은 `time_slot`이 메인 패널과 같은 20종 라벨로 바뀐 동일 구조다.
    """
    out = df.copy()
    start_hour = out["time_slot"].str.split("-").str[0].astype(int)
    late_night = start_hour <= _LATE_NIGHT_MAX_HOUR
    first_train = start_hour == _LATE_NIGHT_MAX_HOUR + 1

    out.loc[late_night, "date"] = out.loc[late_night, "date"] - pd.Timedelta(days=1)
    out.loc[late_night, "time_slot"] = "24~"
    out.loc[first_train, "time_slot"] = "~06"

    group_cols = [c for c in out.columns if c != "passengers"]
    return out.groupby(group_cols, as_index=False, observed=True)["passengers"].sum()


def verify_mass_conservation(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """재배치 전후로 (station_no, direction)별 총합이 같은지 확인한다.

    다른 부분은 전부 같아야 정상이므로, 차이가 있는 행만 돌려준다(빈 프레임이면 통과).
    """
    key = ["station_no", "direction"]
    before_sum = before.groupby(key, observed=True)["passengers"].sum().rename("before")
    after_sum = after.groupby(key, observed=True)["passengers"].sum().rename("after")
    compared = pd.concat([before_sum, after_sum], axis=1)
    return compared[~compared["before"].eq(compared["after"])]


def pivot_directions(df: pd.DataFrame) -> pd.DataFrame:
    """승차/하차를 행에서 열로 편다 — `build_crowd_panel.py`와 동일한 모양을 맞춘다."""
    wide = df.pivot_table(
        index=["date", "station_no", "station_name", "line", "lat", "lon", "time_slot"],
        columns="direction",
        values="passengers",
        aggfunc="sum",
    ).reset_index()
    wide.columns.name = None
    return wide


def build_line9_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = build_line9_daily_long()
    cleaned, _ = drop_conflicting_duplicates(raw)
    enriched = attach_station_master(cleaned)

    reshaped = reshape_to_panel_slots(enriched)
    mass_mismatch = verify_mass_conservation(enriched, reshaped)

    panel = pivot_directions(reshaped)
    panel = attach_calendar(panel)
    weather, _ = prepare_weather()
    panel = attach_weather(panel, weather)

    ordered = [
        "date",
        "station_no",
        "station_name",
        "line",
        "lat",
        "lon",
        "time_slot",
        "boarding",
        "alighting",
        "dow",
        "weekday_ko",
        "is_holiday",
        "is_weekend",
        "day_type",
        *_WEATHER_COLS,
    ]
    return panel[ordered], mass_mismatch


def save_panel(panel: pd.DataFrame) -> Path:
    CROWD_PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = CROWD_PROCESSED / OUTPUT_NAME
    panel.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    panel, mass_mismatch = build_line9_panel()

    if len(mass_mismatch):
        print(f"[경고] 시간대 재배치 전후 합계가 다른 (역, 방향) {len(mass_mismatch)}건:")
        print(mass_mismatch.to_string())
    else:
        print("[확인] 시간대 재배치 전후 (역, 방향)별 합계 일치 — 질량 보존 통과.")

    missing_weather = int(panel["temp_c"].isna().sum())
    if missing_weather:
        print(f"[경고] 기상 미매칭 {missing_weather:,}행 — 구간 경계(24~ 마지막 날) 확인 필요")

    out_path = save_panel(panel)
    print(
        f"저장 완료: {out_path} ({len(panel):,}행, "
        f"{panel['date'].min():%Y-%m-%d}~{panel['date'].max():%Y-%m-%d}, "
        f"역 {panel['station_no'].nunique()}개, 시간대 {panel['time_slot'].nunique()}개)"
    )
    print(
        "[안내] 메인 패널(crowd_panel_2024_2025.parquet)과 스키마는 같지만 날짜 범위가 달라 "
        "합치지 않고 별도 파일로 냈다 — 통합 방식은 이후 결정."
    )


if __name__ == "__main__":
    main()
