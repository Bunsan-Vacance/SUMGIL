"""전체 대여소 좌표 매핑 + target_net_flow 데이터셋 생성 — top300/stratified300 필터 없이.

`stock_q3_mapped_netflow_v5`(Phase 0~3에서 쓴 300개 표본 데이터셋)와 같은 방법론
(`station_mapping_check_report.md`의 좌표 6자리 매칭)을 그대로 쓰되, station 필터를 빼고
전체 대여소를 대상으로 한다. 원본은 `AI/data/BIKE/raw/`에 3종류로 있다.

    rental_history/tpss_bcycl_od_statnhm_YYYYMM/*.csv   5분 단위 대여이력(OD), encoding=cp949
        컬럼: 기준_날짜,집계_기준,기준_시간대,시작_대여소_ID,시작_대여소명,
              종료_대여소_ID,종료_대여소명,전체_건수,전체_이용_분,전체_이용_거리
        `집계_기준`이 "출발시간"/"도착시간" 두 가지로 나뉜다 — 같은 트립을 출발 시각 기준으로도,
        도착 시각 기준으로도 각각 한 행씩 낸 것이다. rent_count_5m은 출발시간 행을
        시작_대여소_ID로, return_count_5m은 도착시간 행을 종료_대여소_ID로 집계한다.

    station_stock_hourly/.../data_YYMM.csv               1시간 단위 재고, encoding=cp949
        컬럼: 일시,대여소번호,대여소명,시간대,거치대수량 — station_no(숫자) 기준.
        거치대수량은 거치대 용량이 아니라 시간대별로 실제 변하는 재고값(확인됨).

    station_master/서울시 공공자전거 따릉이 대여소 마스터 정보.csv   OD측 좌표(ST-xxx + 위경도)
    station_master/공공자전거 대여소 정보(YY.MM월 기준).xlsx        station_no측 좌표(연도별 스냅샷)

station_no ↔ ST-xxx는 숫자로 직접 조인하면 안 된다(대여소 재번호 부여로 다수가 어긋남,
`station_mapping_check_report.md` 참고) — 위경도 6자리 일치, 실패 시 5자리로 매칭한다.

출력 스키마는 `q3-seasonal-dataset-check/src/dataset_report_v5.py`의 EXPECTED_COLUMNS와
동일하게 맞춰, 기존 phase1_baseline.py/phase2_historical_profile.py가 `--train-path` 등
직접 경로 지정 옵션으로 그대로 읽게 할 수 있다 — 단 출력 포맷이 parquet이라(gzip CSV 대비
쓰기 27배·읽기 15배 빠름, scale-probe 실측) 그 스크립트들의 `read_split()`이 확장자를 보고
`pd.read_parquet`도 타게 소폭 patch해야 한다(아직 안 함 — pipeline 승격 단계에서 처리).

실행 예 (스모크 테스트 — 며칠치·소수 station으로 먼저 확인):
    python build_full_station_netflow.py \
        --train-start 2024-01-01 --train-end 2024-01-03 \
        --test-start 2024-01-01 --test-end 2024-01-01 \
        --max-stations 50 --out-dir ../outputs/smoke

전체 실행(2024 전체 train, 2025 Q3 test)은 스모크 결과 확인 후 규모를 올려서 돌린다 —
`AI/CLAUDE.md` 원칙(실행 전 예상 시간 확인, 표본으로 먼저 끝까지 도는지 확인).
"""

from __future__ import annotations

import argparse
import gc
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

AI_DIR = Path(__file__).resolve().parents[4]
RAW_DIR = AI_DIR / "data" / "BIKE" / "raw"

DEFAULT_OD_MASTER = RAW_DIR / "station_master" / "서울시 공공자전거 따릉이 대여소 마스터 정보.csv"
DEFAULT_STATION_INFO_2024 = RAW_DIR / "station_master" / "공공자전거 대여소 정보(24.12월 기준).xlsx"
DEFAULT_STATION_INFO_2025 = RAW_DIR / "station_master" / "공공자전거 대여소 정보(25.12월 기준).xlsx"
DEFAULT_RENTAL_HISTORY_DIR = RAW_DIR / "rental_history"
DEFAULT_STOCK_HOURLY_DIR = RAW_DIR / "station_stock_hourly"

HORIZONS = [5, 10, 15, 30]
SLOT_MINUTES = 5
SHORTAGE_THRESHOLD = 2  # is_empty_anchor 판정 기준(대) — 참고용, 여기선 0대만 empty로 본다


def read_csv_any_encoding(path: Path, **kwargs) -> pd.DataFrame:
    """같은 원천이라도 파일마다 인코딩이 다르다(2024=cp949, 일부 2025=utf-8 확인됨).

    cp949로 먼저 시도하고, 디코딩 에러가 나면 utf-8(BOM 포함)로 재시도한다.
    """
    try:
        return pd.read_csv(path, encoding="cp949", **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="utf-8-sig", **kwargs)


# ── 1. station 좌표 매칭 ──────────────────────────────────────────────────────


def load_od_master(path: Path) -> pd.DataFrame:
    """OD 마스터(ST-xxx + 위경도). 좌표 0.000000(결측) 행은 제외한다."""
    df = pd.read_csv(path, encoding="cp949")
    df = df.rename(
        columns={"대여소_ID": "od_station_id", "위도": "od_lat", "경도": "od_lon"}
    )[["od_station_id", "od_lat", "od_lon"]]
    before = len(df)
    df = df[(df["od_lat"] != 0.0) & (df["od_lon"] != 0.0)].reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        print(f"  [OD 마스터] 좌표 결측(0,0) {dropped}건 제외, {len(df)}행 사용")
    return df


def load_station_info(path: Path) -> pd.DataFrame:
    """station_no측 좌표 스냅샷(공공자전거 대여소 정보 xlsx).

    헤더가 1~5행(1-indexed)에 걸친 병합 셀이라 header=None + skiprows=5로 읽고
    위치로 컬럼명을 붙인다(A=번호, B=명칭, C=자치구, D=주소, E=위도, F=경도, H=LCD거치대수,
    I=QR거치대수, J=구분). 거치대수는 LCD/QR 중 그 대여소가 실제 쓰는 한쪽만 값이 있고
    나머지는 결측이라(확인됨, LCD 1,078 / QR 1,682 / 혼합 6), 두 컬럼을 더해서 쓴다.
    """
    df = pd.read_excel(path, header=None, skiprows=5)
    df = df.iloc[:, [0, 1, 2, 4, 5, 7, 8]].copy()
    df.columns = ["station_no", "station_name", "district", "lat", "lon", "rack_lcd", "rack_qr"]
    df["station_no"] = normalize_station_no(df["station_no"])
    df["rack_count"] = pd.to_numeric(df["rack_lcd"], errors="coerce").fillna(0) + pd.to_numeric(
        df["rack_qr"], errors="coerce"
    ).fillna(0)
    df = df.drop(columns=["rack_lcd", "rack_qr"])
    return df.dropna(subset=["lat", "lon"]).reset_index(drop=True)


def build_station_mapping(
    od_master: pd.DataFrame, station_info: pd.DataFrame
) -> tuple[pd.DataFrame, dict]:
    """좌표 6자리 일치 우선, 실패 시 5자리로 매칭. station_mapping_check_report.md와 동일 방법."""
    od = od_master.copy()
    info = station_info.copy()
    od["key6"] = od["od_lat"].round(6).astype(str) + "," + od["od_lon"].round(6).astype(str)
    info["key6"] = info["lat"].round(6).astype(str) + "," + info["lon"].round(6).astype(str)
    merged6 = od.merge(info, on="key6", how="inner", suffixes=("", "_info"))

    matched_od_ids = set(merged6["od_station_id"])
    od_left = od[~od["od_station_id"].isin(matched_od_ids)].copy()
    info_left = info[~info["station_no"].isin(merged6["station_no"])].copy()

    od_left["key5"] = od_left["od_lat"].round(5).astype(str) + "," + od_left["od_lon"].round(5).astype(str)
    info_left["key5"] = info_left["lat"].round(5).astype(str) + "," + info_left["lon"].round(5).astype(str)
    merged5 = od_left.merge(info_left, on="key5", how="inner", suffixes=("", "_info"))

    mapping = pd.concat(
        [
            merged6[["od_station_id", "station_no", "station_name", "district", "rack_count", "lat", "lon"]],
            merged5[["od_station_id", "station_no", "station_name", "district", "rack_count", "lat", "lon"]],
        ],
        ignore_index=True,
    ).drop_duplicates(subset=["od_station_id"])

    report = {
        "od_master_rows": len(od_master),
        "station_info_rows": len(station_info),
        "matched_6decimal": len(merged6),
        "matched_5decimal_fallback": len(merged5),
        "matched_total": len(mapping),
        "match_ratio_of_od": len(mapping) / len(od_master) if len(od_master) else 0.0,
    }
    return mapping, report


# ── 2. rental_history(5분 OD) 집계 ────────────────────────────────────────────


def _daily_rental_paths(rental_dir: Path, start: pd.Timestamp, end: pd.Timestamp) -> list[Path]:
    paths = []
    d = start
    while d <= end:
        month_dir = rental_dir / f"tpss_bcycl_od_statnhm_{d:%Y%m}"
        p = month_dir / f"tpss_bcycl_od_statnhm_{d:%Y%m%d}.csv"
        if p.exists():
            paths.append(p)
        d += pd.Timedelta(days=1)
    return paths


# rental_history 헤더 텍스트가 월마다 최소 3가지로 다르게 내려받아졌다(확인됨) —
#   ① 기준_날짜,집계_기준,기준_시간대,시작_대여소_ID,시작_대여소명,종료_대여소_ID,종료_대여소명,전체_건수,...
#   ② stdr_de,dvcd,tmzon,start_statn_id,start_statn_nm,end_statn_id,end_statn_nm,cnt,... (영문, utf-8)
#   ③ 기준_날짜,집계_기준,기준_시간,시작_대여소,시작_대여소명,종료_대여소,종료_대여소명,전체건수,... (밑줄 일부 빠짐)
# 이름 매칭은 새 변형이 또 나오면 계속 깨진다 — 세 버전 다 컬럼 "순서"는 동일해서
# 위치 기반으로 고정한다(10개 컬럼: 날짜,집계기준,시간,시작ID,시작명,종료ID,종료명,건수,분,거리).
_RENTAL_COLUMNS = [
    "기준_날짜",
    "집계_기준",
    "기준_시간대",
    "시작_대여소_ID",
    "시작_대여소명",
    "종료_대여소_ID",
    "종료_대여소명",
    "전체_건수",
    "전체_이용_분",
    "전체_이용_거리",
]


def _read_rental_day(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """하루치 파일 → (rent 집계, return 집계). 파일별로 즉시 group-by해서 원본 행은 버린다."""
    df = read_csv_any_encoding(path)
    # 일부 파일은 각 줄 끝에 trailing comma가 있어 빈 열이 하나 더 잡힌다(확인됨,
    # 20240102 등) — 마지막 열이 전부 결측이면 그 열만 버리고 계속 진행한다.
    if len(df.columns) == len(_RENTAL_COLUMNS) + 1 and df.iloc[:, -1].isna().all():
        df = df.iloc[:, :-1]
    if len(df.columns) != len(_RENTAL_COLUMNS):
        raise ValueError(
            f"{path}: 예상 컬럼 수({len(_RENTAL_COLUMNS)})와 다름({len(df.columns)}) — "
            f"실제 헤더: {list(df.columns)}"
        )
    df.columns = _RENTAL_COLUMNS
    df["기준_시간대"] = df["기준_시간대"].astype("int32")
    df["date"] = pd.to_datetime(df["기준_날짜"].astype(str), format="%Y%m%d")
    # 기준_시간대는 HHMM 형식(예: 1750 = 17:50)이다 — 그냥 5로 나누면 시(hour)가 0일 때만
    # 우연히 맞고 그 외엔 다 틀린다(예: 1750//5=350, 정답은 (17*60+50)//5=214). 시/분을
    # 분리해서 하루 5분 슬롯(0~287)으로 정확히 계산한다. (버그로 확인됨 — 시간대별
    # 대여량이 새벽에 튀고 낮에 꺼지는 등 실제 이용 패턴과 안 맞았음)
    hh = df["기준_시간대"] // 100
    mm = df["기준_시간대"] % 100
    df["slot_5m"] = hh * 12 + mm // SLOT_MINUTES

    rent = (
        df[df["집계_기준"] == "출발시간"]
        .groupby(["date", "slot_5m", "시작_대여소_ID"])["전체_건수"]
        .sum()
        .reset_index()
        .rename(columns={"시작_대여소_ID": "od_station_id", "전체_건수": "rent_count_5m"})
    )
    ret = (
        df[df["집계_기준"] == "도착시간"]
        .groupby(["date", "slot_5m", "종료_대여소_ID"])["전체_건수"]
        .sum()
        .reset_index()
        .rename(columns={"종료_대여소_ID": "od_station_id", "전체_건수": "return_count_5m"})
    )
    return rent, ret


def aggregate_rental_history(
    rental_dir: Path, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    paths = _daily_rental_paths(rental_dir, start, end)
    if not paths:
        raise FileNotFoundError(f"rental_history 파일 없음: {rental_dir}, {start.date()}~{end.date()}")
    rent_parts, return_parts = [], []
    for p in paths:
        rent, ret = _read_rental_day(p)
        rent_parts.append(rent)
        return_parts.append(ret)
    rent_all = pd.concat(rent_parts, ignore_index=True)
    return_all = pd.concat(return_parts, ignore_index=True)
    merged = rent_all.merge(return_all, on=["date", "slot_5m", "od_station_id"], how="outer")
    merged["rent_count_5m"] = merged["rent_count_5m"].fillna(0).astype(int)
    merged["return_count_5m"] = merged["return_count_5m"].fillna(0).astype(int)
    merged["net_flow_5m"] = merged["return_count_5m"] - merged["rent_count_5m"]
    return merged


# ── 3. station_stock_hourly(1시간 재고) 집계 ──────────────────────────────────


def _quarter_stock_paths(stock_dir: Path, start: pd.Timestamp, end: pd.Timestamp) -> list[Path]:
    months = sorted({(d.year, d.month) for d in pd.date_range(start, end, freq="D")})
    paths = []
    for year, month in months:
        matches = list(stock_dir.glob(f"*{year}년도*/data_{str(year)[2:]}{month:02d}.csv"))
        paths.extend(matches)
    return paths


def load_stock_hourly(stock_dir: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    paths = _quarter_stock_paths(stock_dir, start, end)
    if not paths:
        raise FileNotFoundError(f"station_stock_hourly 파일 없음: {stock_dir}, {start.date()}~{end.date()}")
    parts = []
    for p in paths:
        df = read_csv_any_encoding(
            p,
            usecols=["일시", "대여소번호", "시간대", "거치대수량"],
            dtype={"대여소번호": str, "시간대": "int32", "거치대수량": "float32"},
        )
        df["date"] = pd.to_datetime(df["일시"])
        mask = (df["date"] >= start) & (df["date"] <= end)
        parts.append(df.loc[mask, ["date", "대여소번호", "시간대", "거치대수량"]])
    out = pd.concat(parts, ignore_index=True)
    out = out.rename(columns={"대여소번호": "station_no", "시간대": "hour", "거치대수량": "stock"})
    out["station_no"] = normalize_station_no(out["station_no"])
    return out


def normalize_station_no(series: pd.Series) -> pd.Series:
    """station_no 표기가 원천마다 다르다(대여소 정보 xlsx="301", 재고 원본="00301") —
    앞자리 0을 떼서 정수 문자열로 통일한다."""
    return pd.to_numeric(series, errors="coerce").astype("Int64").astype(str)


# ── 4. 결합 + target_net_flow ─────────────────────────────────────────────────


def build_target_dataset(
    mapping: pd.DataFrame,
    rental_agg: pd.DataFrame,
    stock_hourly: pd.DataFrame,
) -> pd.DataFrame:
    """rental_agg(5분 슬롯 단위) + station 매핑 + stock_hourly(1시간 anchor) → target_net_flow 표."""
    stock_hourly = stock_hourly.merge(mapping[["od_station_id", "station_no"]], on="station_no", how="inner")
    panel = rental_agg.merge(mapping, on="od_station_id", how="inner")

    panel["datetime_5m"] = panel["date"] + pd.to_timedelta(panel["slot_5m"] * SLOT_MINUTES, unit="m")
    panel["hour"] = panel["datetime_5m"].dt.hour
    panel["minute"] = panel["datetime_5m"].dt.minute
    panel["datetime_hour"] = panel["datetime_5m"].dt.floor("h")
    panel["day_of_week"] = panel["datetime_5m"].dt.dayofweek
    panel["is_weekend"] = panel["day_of_week"] >= 5
    panel["month"] = panel["datetime_5m"].dt.month
    panel["year"] = panel["datetime_5m"].dt.year
    panel["sin_hour"] = np.sin(2 * np.pi * panel["hour"] / 24)
    panel["cos_hour"] = np.cos(2 * np.pi * panel["hour"] / 24)
    n_slots_per_day = 24 * 60 // SLOT_MINUTES
    panel["sin_slot"] = np.sin(2 * np.pi * panel["slot_5m"] / n_slots_per_day)
    panel["cos_slot"] = np.cos(2 * np.pi * panel["slot_5m"] / n_slots_per_day)

    # known_stock_at_request: merge_asof(by=)로 station별 as-of 조인을 한 번에 벡터화한다
    # (station마다 파이썬 for문을 돌리지 않는다 — AI/CLAUDE.md "반복은 벡터화" 원칙).
    # merge_asof는 양쪽 다 on 컬럼 기준 정렬만 요구하고, by가 station 단위 정확 일치를 맡는다.
    stock_hourly = stock_hourly.copy()
    stock_hourly["datetime_hour"] = stock_hourly["date"] + pd.to_timedelta(stock_hourly["hour"], unit="h")
    stock_sorted = stock_hourly.sort_values("datetime_hour")
    panel_sorted = panel.sort_values("datetime_5m")

    # pandas 3.x는 문자열 컬럼을 상황에 따라 object 또는 새 StringDtype으로 다르게
    # 추론한다 — merge_asof(by=)는 두 쪽 dtype이 다르면 에러를 낸다(2024-11 데이터에서
    # 실제로 발생, 이전 달들은 우연히 같은 dtype이라 안 걸렸을 뿐). 둘 다 object로 강제한다.
    panel_sorted["od_station_id"] = panel_sorted["od_station_id"].astype(object)
    stock_sorted["od_station_id"] = stock_sorted["od_station_id"].astype(object)

    panel = pd.merge_asof(
        panel_sorted,
        stock_sorted[["od_station_id", "datetime_hour", "stock"]],
        left_on="datetime_5m",
        right_on="datetime_hour",
        by="od_station_id",
        direction="backward",
        suffixes=("", "_anchor"),
    )
    panel = panel.rename(columns={"stock": "stock_anchor_hour", "datetime_hour_anchor": "stock_anchor_time"})

    panel["minutes_since_stock_anchor"] = (
        (panel["datetime_5m"] - panel.get("stock_anchor_time", pd.NaT)).dt.total_seconds() / 60
    )
    panel["stock_ratio_hour"] = panel["stock_anchor_hour"] / panel["rack_count"].replace(0, np.nan)
    panel["is_empty_anchor"] = panel["stock_anchor_hour"] == 0
    panel["is_full_anchor"] = panel["stock_anchor_hour"] >= panel["rack_count"]

    # target_net_flow: base_time부터 horizon분 뒤까지 forward rolling sum (station별 시계열)
    panel = panel.sort_values(["od_station_id", "datetime_5m"]).reset_index(drop=True)
    panel["base_time"] = panel["datetime_5m"]
    rows_per_station = panel.groupby("od_station_id").cumcount()  # noqa: F841 (디버그용, 제거 가능)

    out_frames = []
    for h in HORIZONS:
        steps = h // SLOT_MINUTES
        g = panel.groupby("od_station_id")
        target_rent = g["rent_count_5m"].transform(lambda s: s.shift(-1).rolling(steps, min_periods=1).sum())
        target_return = g["return_count_5m"].transform(lambda s: s.shift(-1).rolling(steps, min_periods=1).sum())
        sub = panel.copy()
        sub["horizon_min"] = h
        sub["target_rent_count"] = target_rent
        sub["target_return_count"] = target_return
        sub["target_net_flow"] = target_return - target_rent
        out_frames.append(sub)

    result = pd.concat(out_frames, ignore_index=True)
    result = result.rename(columns={"lat": "lat_stock", "lon": "lon_stock"})
    keep_cols = [
        "od_station_id",
        "station_no",
        "station_name",
        "district",
        "lat_stock",
        "lon_stock",
        "rack_count",
        "datetime_5m",
        "datetime_hour",
        "date",
        "year",
        "month",
        "hour",
        "minute",
        "day_of_week",
        "is_weekend",
        "slot_5m",
        "sin_hour",
        "cos_hour",
        "sin_slot",
        "cos_slot",
        "stock_anchor_hour",
        "stock_ratio_hour",
        "minutes_since_stock_anchor",
        "is_empty_anchor",
        "is_full_anchor",
        "rent_count_5m",
        "return_count_5m",
        "net_flow_5m",
        "base_time",
        "horizon_min",
        "target_net_flow",
        "target_rent_count",
        "target_return_count",
    ]
    return result.reindex(columns=keep_cols)


# ── 5. 실행 ───────────────────────────────────────────────────────────────────


class PeakMemoryTracker:
    """백그라운드 스레드로 이 프로세스의 RSS를 주기적으로 재서 최댓값을 남긴다.

    Phase 2.5에서 300개 station만으로도 OOM이 반복됐던 전례가 있어, 전체 대여소로
    스케일업하기 전에 station 수별 피크 메모리를 실측하는 용도(scale-probe)다.
    """

    def __init__(self, interval_sec: float = 1.0) -> None:
        self._interval = interval_sec
        self._peak_bytes = 0
        self._stop = threading.Event()
        self._proc = psutil.Process()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                rss = self._proc.memory_info().rss
                self._peak_bytes = max(self._peak_bytes, rss)
            except psutil.Error:
                pass
            self._stop.wait(self._interval)

    def __enter__(self) -> "PeakMemoryTracker":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval * 2)

    @property
    def peak_mb(self) -> float:
        return round(self._peak_bytes / (1024 * 1024), 1)


@dataclass
class SplitSpec:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp
    station_info_path: Path


def _month_chunks(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """[start, end]를 달력 월 경계로 쪼갠다. 양끝 달은 요청 범위로 잘린다."""
    chunks = []
    cur = start.replace(day=1)
    while cur <= end:
        month_end = cur + pd.offsets.MonthEnd(0)
        chunks.append((max(cur, start), min(month_end, end)))
        cur = cur + pd.DateOffset(months=1)
    return chunks


def build_split(
    spec: SplitSpec, od_master: pd.DataFrame, max_stations: int | None, out_dir: Path, tag: str
) -> list[dict]:
    """월 단위로 쪼개 처리하고 달마다 즉시 parquet으로 쓴다.

    안 쪼개면 요청 기간 전체(예: 12개월)의 패널 + horizon 4종 복사본이 동시에 메모리에
    있어야 해서 역산 ~43GB까지 커진다(500 station·1개월 실측 703MB 기준). 월 단위로
    쪼개면 매 순간 메모리 사용량이 "한 달치"에 고정된다 — 총 처리 시간은 그대로지만
    (같은 양을 처리하는 건 똑같다) OOM 없이 끝까지 도는 게 목적이다.
    station 매핑은 split당 한 번만 계산해 매달 재사용한다(좌표 매칭은 기간과 무관).
    """
    station_info = load_station_info(spec.station_info_path)
    mapping, mapping_report = build_station_mapping(od_master, station_info)
    if max_stations:
        mapping = mapping.head(max_stations)

    chunk_reports = []
    for chunk_start, chunk_end in _month_chunks(spec.start, spec.end):
        t0 = time.time()
        rental_agg = aggregate_rental_history(DEFAULT_RENTAL_HISTORY_DIR, chunk_start, chunk_end)
        rental_agg = rental_agg[rental_agg["od_station_id"].isin(mapping["od_station_id"])]

        stock_hourly = load_stock_hourly(DEFAULT_STOCK_HOURLY_DIR, chunk_start, chunk_end)
        stock_hourly = stock_hourly[stock_hourly["station_no"].isin(mapping["station_no"])]

        dataset = build_target_dataset(mapping, rental_agg, stock_hourly)
        elapsed = time.time() - t0

        out_path = out_dir / f"{spec.name}_netflow_q3_mapped_{tag}_{chunk_start:%Y%m}.parquet"
        t_write0 = time.time()
        dataset.to_parquet(out_path, index=False)
        write_sec = time.time() - t_write0

        chunk_report = {
            "split": spec.name,
            "month": f"{chunk_start:%Y-%m}",
            "elapsed_sec": round(elapsed, 1),
            "write_sec": round(write_sec, 1),
            "rows": len(dataset),
            "stations": dataset["od_station_id"].nunique(),
            "out_path": str(out_path),
            **mapping_report,
        }
        chunk_reports.append(chunk_report)
        print(
            f"  [{spec.name} {chunk_start:%Y-%m}] {out_path.name}: {chunk_report['rows']:,}행, "
            f"{chunk_report['stations']}station, 처리 {chunk_report['elapsed_sec']}초 + "
            f"parquet쓰기 {chunk_report['write_sec']}초"
        )

        # 다음 달로 넘어가기 전에 이번 달치를 메모리에서 확실히 내린다
        # (Phase 2.5: "train_df는 학습 끝나면 del+gc.collect()로 즉시 해제" 관례).
        del rental_agg, stock_hourly, dataset
        gc.collect()

    return chunk_reports


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--train-start", default="2024-01-01")
    p.add_argument("--train-end", default="2024-11-30")
    p.add_argument("--valid-start", default="2024-12-01")
    p.add_argument("--valid-end", default="2024-12-31")
    p.add_argument("--test-start", default="2025-07-01")
    p.add_argument("--test-end", default="2025-09-30")
    p.add_argument("--od-master", default=str(DEFAULT_OD_MASTER))
    p.add_argument("--station-info-2024", default=str(DEFAULT_STATION_INFO_2024))
    p.add_argument("--station-info-2025", default=str(DEFAULT_STATION_INFO_2025))
    p.add_argument("--max-stations", type=int, default=None, help="스모크 테스트용 station 수 제한")
    p.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[1] / "outputs"))
    p.add_argument("--tag", default="full", help="출력 파일명 태그: {split}_netflow_q3_mapped_{tag}.parquet")
    p.add_argument(
        "--splits",
        default="train,valid,test",
        help="처리할 split만 골라서 실행 (예: --splits train). 전체 실행 시 프로세스를 "
        "월별로 새로 띄워 메모리를 리셋하려고 train만 반복 호출할 때 쓴다.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    od_master = load_od_master(Path(args.od_master))

    all_specs = {
        "train": SplitSpec("train", pd.Timestamp(args.train_start), pd.Timestamp(args.train_end), Path(args.station_info_2024)),
        "valid": SplitSpec("valid", pd.Timestamp(args.valid_start), pd.Timestamp(args.valid_end), Path(args.station_info_2024)),
        "test": SplitSpec("test", pd.Timestamp(args.test_start), pd.Timestamp(args.test_end), Path(args.station_info_2025)),
    }
    wanted = [s.strip() for s in args.splits.split(",") if s.strip()]
    specs = [all_specs[s] for s in wanted]

    reports = []
    t_total0 = time.time()
    with PeakMemoryTracker() as mem:
        for spec in specs:
            print(f"[{spec.name}] {spec.start.date()} ~ {spec.end.date()} 처리 중 (월 단위)...")
            chunk_reports = build_split(spec, od_master, args.max_stations, out_dir, args.tag)
            for r in chunk_reports:
                r["peak_memory_mb_so_far"] = mem.peak_mb
            reports.extend(chunk_reports)
    total_elapsed = round(time.time() - t_total0, 1)
    print(f"\n전체 처리 시간: {total_elapsed}초, 피크 메모리: {mem.peak_mb}MB")

    # parquet — gzip CSV 대비 쓰기 27배·읽기 15배 빠르고 크기도 44% 작음(실측,
    # scale-probe/500 참고). phase1_baseline.py 등 기존 스크립트는 --train-path로
    # 직접 넘길 때 read_split()이 확장자를 보고 parquet도 읽게 소폭 patch가 필요하다.
    # 산출물은 split당 여러 개(월별) 파일이라, 그 스크립트들의 nargs="+" 경로 옵션에
    # 그대로 나열해서 넘기면 된다.
    report_df = pd.DataFrame(reports)
    report_df["peak_memory_mb"] = mem.peak_mb
    report_df["total_elapsed_sec"] = total_elapsed
    report_df.to_csv(out_dir / "build_report.csv", index=False)
    print(f"\n완료. 산출물: {out_dir}")
    print(report_df.to_string(index=False))


if __name__ == "__main__":
    main()
