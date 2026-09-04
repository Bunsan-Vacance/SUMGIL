"""지하철 혼잡도 스냅샷 원천(서울시 CSV, 9호선 xlsx)을 tidy long-format으로 정리한다.

두 원천 모두 날짜 컬럼이 없는 "대표 1주 평균" 스냅샷이다 — 자세한 배경은
validation/CROWD/crowd-snapshot-eda/README.md 참고. 요일별 시계열이 아니라
역×시간대×요일유형 단위의 정적 프로파일로 다뤄야 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

_LINE9_SHEET_PATTERN = re.compile(
    r"^(?P<direction>상선|하선)(?P<train_type>일반|급행)\((?P<day_type>평일|휴일)\)$"
)


def load_seoul_congestion_csv(path: str | Path) -> pd.DataFrame:
    """서울교통공사_지하철혼잡도정보.csv(1~8호선, 요일구분 스냅샷)를 long-format으로 로드.

    원본 컬럼: 요일구분, 호선, 역번호, 출발역, 상하구분 + 시간대별 컬럼(5시30분, 6시00분, ...).
    인코딩은 CP949다.
    """
    df = pd.read_csv(path, encoding="cp949")
    id_vars = ["요일구분", "호선", "역번호", "출발역", "상하구분"]
    time_cols = [c for c in df.columns if c not in id_vars]
    long_df = df.melt(id_vars=id_vars, value_vars=time_cols, var_name="time_slot", value_name="congestion_pct")
    return long_df.rename(
        columns={
            "요일구분": "day_type",
            "호선": "line",
            "역번호": "station_no",
            "출발역": "station_name",
            "상하구분": "direction",
        }
    )


def load_line9_workbook(path: str | Path, year: int) -> pd.DataFrame:
    """9호선 역별 시간별 혼잡도 xlsx(연도별)를 long-format으로 로드.

    시트는 방향×열차종별×요일유형 조합(예: "상선일반(평일)") 8개고, 시트마다 1행은
    "기준일자: ..." 대표주간 안내, 2행이 시간대 헤더, 3행부터 역별 값이다.
    `_xlnm._FilterDatabase` 같은 데이터가 아닌 시트는 건너뛴다.

    2020~2022년 파일은 실제 데이터가 40행 안쪽인데도 엑셀 서식이 시트 전체
    범위(최대 104만 행)까지 적용돼 있어 파일 용량이 부풀려져 있다 — 로드 자체는
    정상 동작하지만 참고할 것.
    """
    sheets = pd.read_excel(path, sheet_name=None, header=1)
    frames = []
    for sheet_name, sheet_df in sheets.items():
        match = _LINE9_SHEET_PATTERN.match(sheet_name)
        if match is None:
            continue
        station_col = sheet_df.columns[0]
        time_cols = [c for c in sheet_df.columns[1:] if pd.notna(c)]
        long_df = sheet_df.melt(
            id_vars=[station_col], value_vars=time_cols, var_name="time_slot", value_name="congestion_pct"
        )
        long_df = long_df.rename(columns={station_col: "station_name"})
        long_df["year"] = year
        long_df["line"] = "9호선"
        for key, value in match.groupdict().items():
            long_df[key] = value
        frames.append(long_df)
    return pd.concat(frames, ignore_index=True)
