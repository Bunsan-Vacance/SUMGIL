"""서울교통공사 서울 도시철도 열차운행시각표 파서 — 135번(시간 해상도 분해) 2층의 입력.

원천: 공공데이터포털 15098251 「서울교통공사_서울 도시철도 열차운행시각표」(CSV cp949, 2026-09-01판,
42.3만 행, 1~9호선, 역사코드 458개). 로그인 다운로드라 자동 수집 대상이 아니다 —
`data/CROWD/raw/timetable/` 아래 파일을 읽는다.

원문 컬럼: 고유번호, 호선('1'~'9'), 역사코드('0150' 같은 4자리), 역사명, 주중주말(DAY/SAT/END),
방향(UP/DOWN, 2호선 본선은 IN/OUT), 급행여부('0'/'1'), 열차코드, 열차도착시간(출발역에서는 비어 있음),
열차출발시간, 출발역, 도착역. 2026-09-11 실제 파일로 확인.

## 우리 체계로 맞추는 세 지점

1. **역 매핑** — 역사코드를 정수로 바꾸면 패널 `station_no`와 273/273 일치한다(나머지 185개는 코레일
   직결 구간·9호선 1단계 등 패널 밖 역 → 인벤토리로 남기고 버린다).
2. **방향 라벨 — 코드를 믿지 않고 궤적에서 추론한다.** 같은 UP이 1호선(서울역→청량리, 역번호 증가)에서는
   우리 `하선`이고 7호선(태릉입구→장암, 역번호 감소)에서는 `상선`이다. 2호선 IN 열차가 을지로입구→시청→
   충정로(역번호 감소 = 우리 `외선`)로 달리는 것도 확인됐다. 그래서 (호선, 방향코드)마다 열차 궤적의
   역 순서와 `line_topology.yaml`의 세그먼트 순서를 비교해 **역번호 증가 방향이면 `하선`(순환선은 `내선`),
   감소 방향이면 `상선`(`외선`)** 으로 붙인다 — 88이 실측 상관으로 확정한 규칙(`congestion.ASCENDING`)과
   같은 축이다. 한 (호선, 코드) 안에서 부호가 갈리면 예외로 올린다.
3. **요일유형** — DAY→평일, SAT→토요일, END→일요일. 공휴일은 일요일 시각표(`day_type_to_timetable`).

도착시간이 비어 있는 출발역 행은 출발시간을 도착시간으로 쓴다(그 역을 "지나는" 시각이 필요할 뿐이다).

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_timetable   # 파일 인벤토리·매핑·방향 추론 결과 출력
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.congestion import ASCENDING, CIRCULAR_LABELS, DESCENDING
from app.CROWD.pipeline.topology import load_topology, resolve_segments

AI_ROOT = Path(__file__).resolve().parents[2]
TIMETABLE_RAW = AI_ROOT / "data" / "CROWD" / "raw" / "timetable"
TIMETABLE_INTERIM = AI_ROOT / "data" / "CROWD" / "interim" / "timetable_long.parquet"
PANEL = AI_ROOT / "data" / "CROWD" / "processed" / "crowd_panel_2024_2025.parquet"

COLUMN_MAP = {
    "고유번호": "row_id",
    "호선": "line_raw",
    "역사코드": "station_code",
    "역사명": "station_name",
    "주중주말": "day_code",
    "방향": "direction_code",
    "급행여부": "express_raw",
    "열차코드": "train_id",
    "열차도착시간": "arrival_time",
    "열차출발시간": "departure_time",
    "출발역": "origin",
    "도착역": "terminus",
}
DAY_CODE_MAP = {"DAY": "평일", "SAT": "토요일", "END": "일요일"}


def day_type_to_timetable(day_type: str) -> str:
    """패널 day_type → 시각표 요일유형. 공휴일은 일요일 시각표."""
    return "일요일" if day_type == "휴일" else day_type


def read_timetable_csv(path: Path) -> pd.DataFrame:
    for enc in ("cp949", "utf-8-sig"):
        try:
            raw = pd.read_csv(path, encoding=enc, dtype=str)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"인코딩을 알 수 없다: {path}")
    missing = [c for c in COLUMN_MAP if c not in raw.columns]
    if missing:
        raise ValueError(f"기대한 컬럼이 없다: {missing} (있는 컬럼: {list(raw.columns)})")
    return raw.rename(columns=COLUMN_MAP)


def normalize_line(line_raw: pd.Series) -> pd.Series:
    """'2', '02', '2호선' → '2호선'."""
    digits = line_raw.astype(str).str.extract(r"(\d+)")[0]
    return digits.astype("Int64").astype(str) + "호선"


def map_stations(frame: pd.DataFrame, stations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """역사코드 → station_no. 1차 코드 일치, 2차 (호선, 역명) 일치. (매핑된 프레임, 미매핑 인벤토리)."""
    st = stations[["station_no", "station_name", "line"]].drop_duplicates()
    out = frame.copy()
    code = pd.to_numeric(out["station_code"], errors="coerce").astype("Int64")
    known = set(st["station_no"].astype(int))
    out["station_no"] = code.where(code.isin(known))

    if out["station_no"].isna().any():
        by_name = st.rename(columns={"station_no": "station_no_by_name"})
        out = out.merge(by_name, on=["line", "station_name"], how="left")
        out["station_no"] = out["station_no"].fillna(out["station_no_by_name"])
        out = out.drop(columns="station_no_by_name")

    unmapped = (
        out[out["station_no"].isna()][["line", "station_code", "station_name"]]
        .drop_duplicates()
        .sort_values(["line", "station_code"])
        .reset_index(drop=True)
    )
    return out[out["station_no"].notna()].copy(), unmapped


def _segment_table(stations_present: set[int]) -> pd.DataFrame:
    """토폴로지를 (segment_id, line, circular, station_no, seq) 행으로 편다. 한 역이 여러 세그먼트에 속할 수 있다."""
    segments, _ = resolve_segments(load_topology(), stations_present)
    rows = []
    for sid, seg in enumerate(segments):
        for i, s in enumerate(seg["stations"]):
            rows.append(
                {
                    "segment_id": sid,
                    "seg_line": seg["line"],
                    "circular": bool(seg.get("circular")),
                    "seg_len": len(seg["stations"]),
                    "station_no": int(s),
                    "seq": i,
                }
            )
    return pd.DataFrame(rows)


def infer_direction_map(frame: pd.DataFrame) -> pd.DataFrame:
    """(line, direction_code) → 우리 방향 라벨. 열차 궤적의 역 순번 변화 부호로 정한다.

    한 역이 여러 세그먼트(2호선 본선·성수지선의 성수 등)에 속하므로, 열차마다 **그 열차의 역을 가장 많이
    담는 세그먼트**를 골라 그 안에서 순번 변화 부호를 본다. 순환선은 wrap(243→201) 스텝을 뺀다.
    반환: (열차별 방향표 [line, direction_code, day_type, train_id, segment_id, direction],
          진단표 [line, direction_code, segment_id, direction, n_trains, agree_ratio]).
    """
    seg_tab = _segment_table(set(frame["station_no"].astype(int)))
    keys = ["line", "direction_code", "day_type", "train_id"]
    f = frame[[*keys, "station_no", "pass_time"]].copy()
    f["station_no"] = f["station_no"].astype(int)
    f = f.merge(seg_tab, on="station_no", how="inner")
    f = f[f["seg_line"] == f["line"]]
    f = f.sort_values([*keys, "segment_id", "pass_time"])

    grp = f.groupby([*keys, "segment_id"], observed=True)
    f["n_in_seg"] = grp["station_no"].transform("count")
    step = grp["seq"].diff()
    step = step.where(~f["circular"] | (step.abs() < f["seg_len"] / 2))
    f["sign"] = np.sign(step)

    per_seg = (
        f.groupby([*keys, "segment_id", "circular"], observed=True)
        .agg(n_in_seg=("n_in_seg", "first"), sign=("sign", "mean"))
        .reset_index()
        .dropna(subset=["sign"])
    )
    # 열차마다 역을 가장 많이 담는 세그먼트 하나 → 그 세그먼트 안 부호로 열차 방향을 정한다.
    best = per_seg.sort_values("n_in_seg", ascending=False).drop_duplicates(keys).copy()
    asc = best["sign"] > 0
    best["direction"] = np.where(asc, ASCENDING, DESCENDING)
    best.loc[best["circular"], "direction"] = best.loc[best["circular"], "direction"].map(
        CIRCULAR_LABELS
    )

    # 진단표: (호선, 코드, 세그먼트) 안에서 부호가 얼마나 일치하는가. 2호선 UP은 신정지선(번호 증가)과
    # 성수지선(번호 감소)을 함께 담아 (호선, 코드) 단위로는 반으로 갈리지만 세그먼트 단위로는 일치한다.
    rows = []
    for (line, code, sid), s in best.groupby(
        ["line", "direction_code", "segment_id"], observed=True
    ):
        pos = float((s["sign"] > 0).mean())
        rows.append(
            {
                "line": line,
                "direction_code": code,
                "segment_id": int(sid),
                "direction": s["direction"].mode().iloc[0],
                "n_trains": len(s),
                "agree_ratio": round(max(pos, 1 - pos), 3),
            }
        )
    summary = pd.DataFrame(
        rows,
        columns=["line", "direction_code", "segment_id", "direction", "n_trains", "agree_ratio"],
    )
    weak = summary[summary["agree_ratio"] < 0.9]
    if len(weak):
        raise ValueError(
            "(호선, 방향코드, 세그먼트) 안에서 진행 방향이 갈린다 — 확인 필요:\n"
            + weak.to_string(index=False)
        )
    per_train = best[[*keys, "segment_id", "direction"]]
    return per_train, summary


def build_timetable_long(
    path: Path, stations: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """CSV → (long 테이블, 미매핑 역 인벤토리, 방향 매핑표).

    long 컬럼: station_no, line, direction, day_type, train_id, arrival_time, departure_time,
    pass_time(도착 없으면 출발), express, origin, terminus, direction_code.
    """
    raw = read_timetable_csv(path)
    raw["line"] = normalize_line(raw["line_raw"])
    raw["day_type"] = raw["day_code"].str.strip().str.upper().map(DAY_CODE_MAP)
    if raw["day_type"].isna().any():
        bad = sorted(raw.loc[raw["day_type"].isna(), "day_code"].unique())
        raise ValueError(f"주중주말 코드 매핑이 없다: {bad}")
    raw["express"] = (
        raw["express_raw"].astype(str).str.strip().isin(["1", "Y", "급행", "TRUE", "True"])
    )
    raw["pass_time"] = raw["arrival_time"].fillna(raw["departure_time"])
    raw = raw.dropna(subset=["pass_time"])
    raw["direction_code"] = raw["direction_code"].astype(str).str.strip().str.upper()

    mapped, unmapped = map_stations(raw, stations)
    mapped["station_no"] = mapped["station_no"].astype(int)
    per_train, dir_map = infer_direction_map(mapped)
    mapped = mapped.merge(
        per_train[["line", "direction_code", "day_type", "train_id", "direction"]],
        on=["line", "direction_code", "day_type", "train_id"],
        how="left",
    )
    # 궤적이 한 역뿐이라 방향을 못 정한 열차(진단용): 방향 NaN으로 남긴다

    cols = [
        "station_no",
        "line",
        "direction",
        "direction_code",
        "day_type",
        "train_id",
        "arrival_time",
        "departure_time",
        "pass_time",
        "express",
        "origin",
        "terminus",
    ]
    out = mapped[cols].sort_values(["line", "station_no", "direction", "day_type", "pass_time"])
    return out.reset_index(drop=True), unmapped, dir_map


def load_stations_from_panel() -> pd.DataFrame:
    return pd.read_parquet(PANEL, columns=["station_no", "station_name", "line"]).drop_duplicates(
        "station_no"
    )


def main() -> None:
    files = sorted(TIMETABLE_RAW.glob("*.csv"))
    if not files:
        print(f"시각표 CSV가 없다: {TIMETABLE_RAW} — 공공데이터포털 15098251에서 받아 넣을 것")
        return
    stations = load_stations_from_panel()
    frames, gaps = [], []
    for f in files:
        long, unmapped, dir_map = build_timetable_long(f, stations)
        frames.append(long)
        gaps.append(unmapped.assign(file=f.name))
        print(
            f"[{f.name}] {len(long):,}행, 역 {long['station_no'].nunique()}개, 미매핑 {len(unmapped)}역"
        )
        print("\n[방향 추론 — (호선, 코드) → 우리 라벨]")
        print(dir_map.to_string(index=False))
    out = pd.concat(frames, ignore_index=True)
    TIMETABLE_INTERIM.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(TIMETABLE_INTERIM, index=False)
    gap_frame = pd.concat(gaps, ignore_index=True)
    if len(gap_frame):
        print(f"\n[미매핑 역 {len(gap_frame)}개 — 패널 밖(코레일 직결·9호선 1단계 등)]")
        print(gap_frame.groupby("line").size().to_string())
    per_day = out.groupby(["line", "day_type"], observed=True)["train_id"].nunique()
    print("\n[호선·요일유형별 열차 수]")
    print(per_day.to_string())
    print(f"\n저장: {TIMETABLE_INTERIM} ({len(out):,}행)")


if __name__ == "__main__":
    main()
