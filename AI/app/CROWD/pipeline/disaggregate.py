"""시간 해상도 분해 — 1시간 승하차 → 30분 → 열차 단위 추정치. 순수 함수(135번).

승하차 원천은 1시간 20슬롯, 혼잡도 스냅샷은 30분 39슬롯, 서비스가 원하는 단위는 열차 한 대다.
날짜별 30분 이하 실측은 어느 공개 원천에도 없으므로 **가정을 명시한 분해(temporal disaggregation)**로
파생 라벨을 만든다. 만들어 채우는 값이라 컬럼에 `_est` 접미를 붙이고(원칙 4), 근거가 없는 셀은
채우지 않는다(원칙 8).

## 1층 — 1시간 → 30분 (`split_hourly_to_30min`)

88 배율표의 같은 1시간 안 두 30분 배율은 분모(raw 1시간 평균)가 같으므로
`ratio_a : ratio_b = 실측_a : 실측_b`, 즉 **그 1시간 안에서 전반/후반 30분의 재차인원 비중**이다
(Notion "혼잡도 시간 해상도": 러시 시간대 표준편차 3.7~5.2%p로 역·방향 불문 안정). 이 비중을
승하차에도 적용한다 — **"재차인원 모양 = 승하차 모양"이 이 층의 가정**이다. 비중은 역·요일유형·
1시간 단위로 방향 평균을 쓴다(승하차는 방향이 없다). 배율표가 없는 (역, 요일유형, 시간)은 NaN.
`~06`은 30분 슬롯이 하나(05:30)라 비중 1, `24~`는 00:00·00:30 둘이다.

## 2층 — 30분 → 열차 (`allocate_to_trains`)

그 30분 슬롯에 그 역·방향을 지난 열차 목록(시각표)에 재차인원을 배분한다. 배차 간격이 짧을 때
승객은 시각표를 보지 않고 도착하므로(대중교통 대기시간 연구의 표준 가정 — 무작위 도착, 평균 대기 =
배차/2) **열차 i의 몫 = 직전 열차와의 간격 ÷ 슬롯 길이**다. 간격이 `long_headway_min`(기본 12분)을
넘는 열차는 `headway_long=True`로 표시한다 — 그 구간(심야·막차)에서는 시각표 의존 도착이 되어 균등
가정이 약해진다. 값은 그대로 두고 플래그만 남겨 소비자가 판단한다.

슬롯 첫 열차의 "직전 열차"는 슬롯 경계 이전 마지막 열차다(경계를 넘어 계산). 슬롯에 열차가 없으면
그 슬롯 재차인원은 배분할 곳이 없어 NaN으로 남긴다(운행 없음 = 혼잡도 정의 불가).

### 배차 의존 도착 혼합 (92)

간격 비례는 "승객이 시각표를 보지 않고 온다"는 가정이고, 문헌상 배차 5분까지는 확실하고 10~15분에서는
승객이 시각표에 맞춰 온다(Luethi·Weidmann·Nash 2007, Bowman·Turnquist 1981). 시각표에 맞춰 오는
승객은 **간격이 아니라 열차를 고른다** — 간격이 5분·25분인 두 열차가 한 슬롯에 있을 때 무작위 도착은
1:5로 나누지만 시각표 도착은 1:1에 가깝다. 그래서 `mix_h0`를 주면 열차 몫을

    share_i ∝ w(h_i) · h_i / Σh  +  (1 − w(h_i)) · 1 / n_slot,   w(h) = 1 (h ≤ h0), 선형 감소, 0 (h ≥ h1)

로 섞고 슬롯 안에서 다시 정규화한다(질량 보존). `mix_h0=None`(기본)이면 기존 간격 비례 그대로다.
`headway_long` 플래그는 혼합과 무관하게 `long_headway_min` 기준으로 남긴다(91 API 소비자 호환).

## 3층 — 열차 → 노드 상태 (239)

2층 출력(열차 한 대 = 한 행)은 아직 "역·방향·시각표" 관점이다. 서비스가 실제로 묻는 것은
"이 역에 이 열차가 들어올 때/나갈 때 얼마나 찼나"이므로 열차 궤적을 따라 값을 노드 관점으로
재색인한다(L5, `RESOLUTION_LADDER.md` §1.1·§3 L5). 새 정보를 만들지 않고 이미 있는 `load_est`를
옮겨 붙일 뿐이다(원칙 4·8 그대로 적용).

- `node_states`: 같은 `train_id`를 도착 시각 순으로 이어 직전 정차역의 출발 재차를 이 역의
  도착 재차로 붙인다(`onboard_arr_est`). 배차 간격이 `max_gap_min`을 넘으면 같은 열차 번호라도
  새 `run_id`로 끊는다(운행 재사용). 위상(`adjacency`)이 주어지면 역 순서가 실제로 인접하지
  않은 구간은 `onboard_arr_est`를 NaN(`arr_source="gap"`)으로 남긴다. 강동처럼 한 역이 여러
  세그먼트에 걸치는 경우(`link_segments`) 실제로 이어지는(다음 역, 없으면 직전 역) 세그먼트를
  남기고, 판단이 안 되면 135번 규칙대로 최대 재차 행을 남기되 `link_ambiguous`로 표시한다
  (숨기지 않는다, 원칙 8).
- `allocate_flows_to_trains`: 방향이 없는 역 단위 30분 승하차(1층 산출)를 그 슬롯의 모든
  방향·열차에 질량 보존으로 나눈다. 기본(`rule="share"`)은 2층 몫에 방향 가중(그 방향 출발
  재차 비율)을 곱하고, `rule="load"`는 재차인원에 비례한다(§1.3 "하차 몫은 승차 몫과 같은
  규칙이 기본" 근거).
- `platform_accumulation`: 표에 분 단위 행을 만들지 않고 함수로 제공한다(§1.3). 배차가 짧으면
  (≤`mix_h0`) 선형 누적, 길면 Luethi 이동 Johnson SB 누적분포와 섞는다(L6, 선택·미검증 —
  "추정" 라벨 필요).

## 검증 가능성

- 1층: 두 30분 추정치의 합 = 1시간 원본(질량 보존). 요일유형 홀드아웃으로 모양 오차 측정.
- 2층: 열차 몫의 합 = 슬롯 재차인원(질량 보존). 외부 실측(열차별 혼잡도)이 없어 정확도는 미검증 —
  서울교통공사 칸별 실시간 혼잡도 개방 시 재판정(계획 파일 참고).
- 3층: 재색인일 뿐이라 별도 검증 대상이 없다(L4와 동일). `platform_accumulation`은 취리히
  사전값 기반 가정이라 서울 실측으로 검증되지 않았다 — 등급으로 바꾸지 않는다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

from app.CROWD.pipeline.congestion import hour_bucket_to_30min_slots
from app.CROWD.pipeline.features import SLOT_ORDER
from app.CROWD.pipeline.lookup import TARGETS

SLOT_MINUTES = 30
LONG_HEADWAY_MIN = 12.0
# 도착 혼합 기본 임계(분): h0까지 무작위 도착 가중 1, h1부터 0. 문헌(5분 확실, 10~15분 시각표 의존).
MIX_H0_DEFAULT = 5.0
MIX_H1_DEFAULT = 15.0


# ── 1층 ──
def half_hour_shares(calibration: pd.DataFrame) -> pd.DataFrame:
    """배율표 → (station_no, day_type, time_slot[1시간], time_slot_30min) 별 전반/후반 비중.

    방향별 비중을 먼저 구한 뒤 방향 평균을 낸다. 한 30분만 있는 시간(`~06`)은 비중 1.
    반환 컬럼: station_no, day_type, time_slot, time_slot_30min, share.
    """
    cal = calibration.dropna(subset=["ratio"]).copy()
    # 배율표의 `time_slot`은 30분 슬롯('08:30')이다. 소속 1시간 버킷('08-09')을 따로 만든다.
    cal["time_slot_30min"] = cal["time_slot"].astype(str)
    cal["hour_bucket"] = cal["time_slot_30min"].map(_slot30_to_hour_bucket)
    key = ["station_no", "direction", "day_type", "hour_bucket"]
    total = cal.groupby(key, observed=True)["ratio"].transform("sum")
    cal["share_dir"] = np.where(total > 0, cal["ratio"] / total, np.nan)
    out = (
        cal.groupby(["station_no", "day_type", "hour_bucket", "time_slot_30min"], observed=True)[
            "share_dir"
        ]
        .mean()
        .rename("share")
        .reset_index()
        .rename(columns={"hour_bucket": "time_slot"})
    )
    # 방향 평균 뒤 합이 1에서 어긋날 수 있어 1시간 안에서 다시 정규화한다.
    norm = out.groupby(["station_no", "day_type", "time_slot"], observed=True)["share"].transform(
        "sum"
    )
    out["share"] = np.where(norm > 0, out["share"] / norm, np.nan)
    return out


def _slot30_to_hour_bucket(slot30: str) -> str:
    hh = int(slot30[:2])
    if hh == 5:
        return "~06"
    if hh == 0:
        return "24~"
    return f"{hh:02d}-{hh + 1:02d}"


def split_hourly_to_30min(
    panel: pd.DataFrame,
    calibration: pd.DataFrame,
    value_cols: Sequence[str] = TARGETS,
    suffix: str = "_30min_est",
) -> pd.DataFrame:
    """1시간 패널 행을 30분 행으로 펼치고 `value_cols`를 비중대로 나눈다.

    `panel`은 date·station_no·day_type·time_slot + value_cols. 반환은 행마다 `time_slot_30min`과
    `{col}{suffix}`, `share`가 붙은 프레임(비중 없는 셀은 NaN). 두 30분 합은 1시간 원본과 같다.
    """
    shares = half_hour_shares(calibration)
    out = panel.copy()
    out["time_slot_30min"] = out["time_slot"].map(hour_bucket_to_30min_slots)
    out = out.explode("time_slot_30min", ignore_index=True)
    out = out.merge(
        shares, on=["station_no", "day_type", "time_slot", "time_slot_30min"], how="left"
    )
    for c in value_cols:
        out[f"{c}{suffix}"] = out[c] * out["share"]
    return out


# ── 2층 ──
def _to_minutes(t: pd.Series) -> pd.Series:
    """'HH:MM' 또는 'HH:MM:SS' → 운행일 기준 분(00~02시는 24시 이후로 접는다)."""
    parts = t.astype(str).str.split(":", expand=True)
    minutes = parts[0].astype(int) * 60 + parts[1].astype(int)
    return minutes.where(minutes >= 4 * 60, minutes + 24 * 60)


def slot30_start_minutes(slot30: str) -> int:
    hh, mm = int(slot30[:2]), int(slot30[3:5])
    m = hh * 60 + mm
    return m + 24 * 60 if hh < 4 else m


def arrival_mix_weight(headway_min, h0: float = MIX_H0_DEFAULT, h1: float = MIX_H1_DEFAULT):
    """무작위 도착 가중 w(h): h ≤ h0 → 1, h ≥ h1 → 0, 사이는 선형. 배열·스칼라 모두 받는다."""
    if h1 <= h0:
        raise ValueError(f"h1({h1})은 h0({h0})보다 커야 한다")
    h = np.asarray(headway_min, dtype=float)
    return np.clip((h1 - h) / (h1 - h0), 0.0, 1.0)


def allocate_to_trains(
    slot_loads: pd.DataFrame,
    timetable: pd.DataFrame,
    load_col: str = "onboard_30min_est",
    long_headway_min: float = LONG_HEADWAY_MIN,
    mix_h0: float | None = None,
    mix_h1: float = MIX_H1_DEFAULT,
    extra_key: Sequence[str] = (),
) -> pd.DataFrame:
    """30분 슬롯 재차인원을 그 슬롯의 열차에 배분한다 — 기본은 간격 비례, `mix_h0`를 주면 도착 혼합.

    `slot_loads`: date, station_no, direction, day_type, time_slot_30min, `load_col`
    (`extra_key`를 주면 그 컬럼도 있어야 한다). `timetable`: station_no, direction, day_type,
    train_id, arrival_time('HH:MM[:SS]')(`extra_key` 컬럼도 있어야 한다).
    반환: 열차 한 대 = 한 행. `load_est`(몫), `headway_min`, `headway_long`, `share`,
    혼합을 썼으면 `mix_w`(그 열차의 무작위 도착 가중).
    슬롯에 열차가 없으면 그 슬롯은 반환에 나오지 않는다(호출자가 NaN으로 취급).

    `extra_key`(239): 슬롯 배정 키에 더할 컬럼(예: 링크 id) — 같은 역·방향·요일유형·슬롯이라도
    이 컬럼 값이 다르면 다른 슬롯으로 취급해 열차 수·몫·질량을 값마다 따로 보존한다. 강동처럼
    한 역에 토폴로지 세그먼트가 여럿 겹칠 때 열차 수·재차인원이 실제로 그 링크를 지나는 열차만
    반영하지 못하던 문제(135 버그)의 수정이다. 배차 간격(`headway_min`)은 `extra_key`와 무관하게
    그 역·방향의 실제 열차 도착 순서로 잰다 — 승강장에서 체감하는 간격은 그 열차가 어느 링크로
    이어지는지와 무관하기 때문이다. `timetable`에 `extra_key` 컬럼이 없으면 어느 컬럼이 빠졌는지
    밝힌 `ValueError`를 낸다.
    """
    for col in extra_key:
        if col not in timetable.columns:
            raise ValueError(f"timetable에 extra_key 컬럼이 없다: {col!r}")

    tt = timetable.copy()
    tt["arr_min"] = _to_minutes(tt["arrival_time"])
    tt = tt.sort_values(["station_no", "direction", "day_type", "arr_min"]).reset_index(drop=True)
    tt["headway_min"] = tt.groupby(["station_no", "direction", "day_type"], observed=True)[
        "arr_min"
    ].diff()
    # 첫차는 직전 열차가 없다 → 슬롯 길이로 둔다(하한 가정, 플래그는 별도)
    tt["headway_min"] = tt["headway_min"].fillna(float(SLOT_MINUTES))
    tt["slot_start"] = (tt["arr_min"] // SLOT_MINUTES) * SLOT_MINUTES
    tt["time_slot_30min"] = tt["slot_start"].map(_minutes_to_slot30)

    key = ["station_no", "direction", "day_type", *extra_key, "time_slot_30min"]
    grp = tt.groupby(key, observed=True)
    tt["share"] = tt["headway_min"] / grp["headway_min"].transform("sum")
    cols = [*key, "train_id", "arrival_time", "headway_min", "share", "headway_long"]
    if mix_h0 is not None:
        w = arrival_mix_weight(tt["headway_min"].to_numpy(), mix_h0, mix_h1)
        n_slot = grp["train_id"].transform("count").to_numpy()
        raw = w * tt["share"].to_numpy() + (1.0 - w) / n_slot
        tt["share"] = raw
        tt["share"] = tt["share"] / grp["share"].transform("sum")  # 슬롯 안 재정규화(질량 보존)
        tt["mix_w"] = w
        cols.append("mix_w")
    tt["headway_long"] = tt["headway_min"] > long_headway_min

    merged = slot_loads.merge(tt[cols], on=key, how="inner")
    merged["load_est"] = merged[load_col] * merged["share"]
    return merged


def _minutes_to_slot30(m: int) -> str:
    m = int(m) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


# 239: `timetable.py`가 `allocate_to_trains`와 정확히 같은 슬롯 배정 규칙을 쓰도록 공개 별칭을 둔다
# (비공개 함수를 그대로 import하는 대신 — 이름만 공개해 계약을 명시한다).
to_minutes = _to_minutes
minutes_to_slot30 = _minutes_to_slot30


def slots_in_order() -> list[str]:
    """운행일 순서의 30분 슬롯 39개(05:30 … 00:30)."""
    out: list[str] = []
    for bucket in SLOT_ORDER:
        out.extend(hour_bucket_to_30min_slots(bucket))
    return out


# ── 3층 ──
def _flow_out_name(col: str, suffix: str) -> str:
    """`_30min_est` 접미를 떼고 `suffix`를 붙인 열차 단위 출력 컬럼명을 만든다."""
    base = col.removesuffix("_30min_est")
    return f"{base}{suffix}"


def _segment_has_adjacent(stations: Sequence[int], a, b) -> bool:
    """세그먼트 역 목록에서 a·b가 순서 무관하게 인접한 쌍으로 나오는지."""
    for i in range(len(stations) - 1):
        if (stations[i] == a and stations[i + 1] == b) or (
            stations[i] == b and stations[i + 1] == a
        ):
            return True
    return False


def _segment_is_terminal(stations: Sequence[int], station_no) -> bool:
    """세그먼트의 첫 역 또는 마지막 역이 station_no인지(종점 링크 판정, prev·next 둘 다 없을 때만 씀)."""
    return len(stations) > 0 and (stations[0] == station_no or stations[-1] == station_no)


# 239: `timetable.assign_links`가 여기와 정확히 같은 인접·종점 판정을 쓰도록 공개 별칭을 둔다
# (`to_minutes`/`minutes_to_slot30`와 같은 방식 — 비공개 함수를 그대로 import하는 대신 이름만
# 공개해 계약을 명시한다).
segment_has_adjacent = _segment_has_adjacent
segment_is_terminal = _segment_is_terminal


def train_trajectory(
    timetable_rows: pd.DataFrame,
    *,
    max_gap_min: float = 20.0,
) -> pd.DataFrame:
    """열차 궤적(런·직전/다음 역)을 계산하는 순수 함수(239) — `node_states`와
    `timetable.assign_links`가 정확히 같은 위상 규칙을 쓰도록 공유한다.

    입력에는 `line, day_type, train_id, station_no, arrival_time`이 있어야 하고, 그 밖의 컬럼은
    그대로 보존한다. 도착 시각순으로 정렬해 같은 (line, day_type, train_id) 안에서 직전 행과의
    간격이 `max_gap_min`을 넘으면 새 `run_id`로 끊는다(운행 재사용 — 2호선 순환 등 같은 열차
    번호를 하루 여러 번 씀). 반환은 (line, day_type, train_id, run_id, 도착시각) 순 정렬 +
    `run_id`·`prev_station_no`·`next_station_no`(같은 런 안에서 shift, 런의 양 끝은 NaN)가 붙은
    프레임이다. 계산에만 쓴 `arr_min`은 버린다.
    """
    train_group = ["line", "day_type", "train_id"]
    traj = timetable_rows.copy()
    traj["arr_min"] = _to_minutes(traj["arrival_time"])
    traj = traj.sort_values([*train_group, "arr_min"], kind="mergesort").reset_index(drop=True)

    gap = traj.groupby(train_group, observed=True)["arr_min"].diff()
    traj["_new_run"] = (gap.isna() | (gap > max_gap_min)).astype(int)
    traj["run_id"] = traj.groupby(train_group, observed=True)["_new_run"].cumsum() - 1
    traj = traj.drop(columns=["_new_run"])

    run_group = [*train_group, "run_id"]
    rg = traj.groupby(run_group, observed=True)
    traj["prev_station_no"] = rg["station_no"].shift(1)
    traj["next_station_no"] = rg["station_no"].shift(-1)

    traj = traj.sort_values([*train_group, "run_id", "arr_min"], kind="mergesort").reset_index(
        drop=True
    )
    return traj.drop(columns=["arr_min"])


def _resolve_link_duplicates(
    df: pd.DataFrame,
    stop_id: list[str],
    link_col: str,
    link_segments: dict[str, list[int]] | None,
) -> pd.DataFrame:
    """(열차, 도착시각, 역)이 여러 토폴로지 세그먼트에 겹쳐 중복된 행을 하나로 줄인다(강동 케이스, 135).

    `prev_station_no`/`next_station_no`가 이미 병합돼 있어야 한다(위상 계산 이후 호출).
    다음 역이 있으면 그 역과 실제로 이어지는 세그먼트, 없으면(종점) 직전 역과 이어지는 세그먼트를
    남긴다 — "역이 세그먼트의 첫/끝"이라는 조건만으로는 강동처럼 한 역에 접한 세그먼트가 여럿일 때
    (본선·하남선·마천선 모두 2549를 경계로 갖는다) 유일하게 정해지지 않아, 실제로 열차가 지나온·
    갈 방향의 간선(prev↔station 또는 station↔next)을 요구하는 쪽으로 좁혔다(스펙 문구의 "첫/끝"
    규칙을 그대로 두면 예시 자체가 모호해지는 문제가 있어 이렇게 보강함). prev·next가 둘 다 없는
    퇴화 케이스(런이 한 행뿐)만 세그먼트 첫/끝 규칙으로 되돌아간다. 그래도 안 정해지거나
    `link_segments`가 없으면 `load_est`가 가장 큰 행을 남기고 `link_ambiguous=True`로 표시한다
    (숨기지 않는다, 원칙 8).
    """
    out = df.copy()
    out["link_ambiguous"] = False
    has_link_col = link_col in out.columns
    dup_mask = out.duplicated(subset=stop_id, keep=False)
    if not dup_mask.any():
        return out

    drop_idx: list = []
    for _, group in out[dup_mask].groupby(stop_id, sort=False, observed=True):
        chosen = None
        if link_segments is not None and has_link_col:
            station_no = group["station_no"].iloc[0]
            next_station = group["next_station_no"].iloc[0]
            prev_station = group["prev_station_no"].iloc[0]
            candidates = []
            for idx, row in group.iterrows():
                stations = link_segments.get(row[link_col], [])
                if pd.notna(next_station):
                    ok = _segment_has_adjacent(stations, station_no, next_station)
                elif pd.notna(prev_station):
                    ok = _segment_has_adjacent(stations, station_no, prev_station)
                else:
                    ok = _segment_is_terminal(stations, station_no)
                if ok:
                    candidates.append(idx)
            if len(candidates) == 1:
                chosen = candidates[0]
        if chosen is None:
            valid = group["load_est"].dropna()
            chosen = valid.idxmax() if not valid.empty else group.index[0]
            out.loc[chosen, "link_ambiguous"] = True
        drop_idx.extend(i for i in group.index if i != chosen)
    return out.drop(index=drop_idx).reset_index(drop=True)


def node_states(
    train_rows: pd.DataFrame,
    *,
    adjacency: set[tuple[int, int]] | None = None,
    link_segments: dict[str, list[int]] | None = None,
    link_col: str = "segment",
    max_gap_min: float = 20.0,
) -> pd.DataFrame:
    """열차 표(2층, `allocate_to_trains` 출력)를 열차 궤적 순으로 이어 노드(역) 상태로 재색인한다(L5, 239).

    입력에는 `line, day_type, station_no, direction, train_id, arrival_time, time_slot_30min,
    load_est, train_capacity`가 있어야 한다. `load_est`는 그 역을 떠날 때 재차인원이다. 이미 있는
    값을 직전 정차역 → 이 역으로 옮겨 붙일 뿐 새 정보를 만들지 않는다(원칙 4·8).

    반환은 입력 컬럼 그대로에 `run_id, prev_station_no, next_station_no, onboard_arr_est,
    onboard_dep_est, load_arr_est, load_dep_est, arr_source, link_ambiguous`를 더한 프레임이고,
    (line, day_type, train_id, run_id, 도착시각) 순으로 정렬해 반환한다.
    """
    df = train_rows.copy()
    df["arr_min"] = _to_minutes(df["arrival_time"])
    train_group = ["line", "day_type", "train_id"]
    stop_id = [*train_group, "arrival_time", "station_no"]
    run_group = [*train_group, "run_id"]

    # 위상(역 순서·런)은 링크와 무관하므로 (열차, 도착시각, 역) 대표 행 하나로 먼저 정하고,
    # 궤적 계산 자체는 공유 함수로 뽑아냈다(239) — `timetable.assign_links`가 같은 규칙을 쓴다.
    dedup = df.drop_duplicates(subset=stop_id, keep="first")
    traj = train_trajectory(dedup, max_gap_min=max_gap_min)

    topo = traj[[*stop_id, "run_id", "prev_station_no", "next_station_no"]]
    df = df.merge(topo, on=stop_id, how="left")

    df = _resolve_link_duplicates(df, stop_id, link_col, link_segments)

    df = df.sort_values([*train_group, "run_id", "arr_min"], kind="mergesort").reset_index(
        drop=True
    )
    rg2 = df.groupby(run_group, observed=True)
    is_first = rg2.cumcount() == 0
    prev_load = rg2["load_est"].shift(1)
    df["onboard_arr_est"] = np.where(is_first, 0.0, prev_load)
    df["arr_source"] = np.where(is_first, "origin", "prev_stop")

    if adjacency is not None:
        prev_arr = df["prev_station_no"].to_numpy()
        cur_arr = df["station_no"].to_numpy()
        valid_prev = ~pd.isna(prev_arr)
        pair_ok = np.zeros(len(df), dtype=bool)
        if valid_prev.any():
            pairs = zip(prev_arr[valid_prev].astype(int), cur_arr[valid_prev].astype(int))
            pair_ok[valid_prev] = [p in adjacency for p in pairs]
        gap_mask = (~is_first.to_numpy()) & (~pair_ok)
        df.loc[gap_mask, "onboard_arr_est"] = np.nan
        df.loc[gap_mask, "arr_source"] = "gap"

    df["onboard_dep_est"] = df["load_est"]
    df["load_dep_est"] = df["load_est"] / df["train_capacity"] * 100.0
    df["load_arr_est"] = df["onboard_arr_est"] / df["train_capacity"] * 100.0

    df = df.drop(columns=["arr_min"]).reset_index(drop=True)
    return df


def allocate_flows_to_trains(
    slot_flows: pd.DataFrame,
    node_rows: pd.DataFrame,
    *,
    flow_cols: Sequence[str] = ("boarding_30min_est", "alighting_30min_est"),
    rule: str = "share",
    out_suffix: str = "_train_est",
) -> pd.DataFrame:
    """방향 없는 역 단위 30분 승하차(1층)를 그 슬롯의 모든 방향·열차에 질량 보존으로 나눈다.

    `slot_flows`: date, station_no, time_slot_30min + `flow_cols`(승하차는 방향이 없다).
    `node_rows`: `node_states` 출력(date, station_no, direction, time_slot_30min, share,
    onboard_arr_est, onboard_dep_est가 있어야 한다).

    `rule="share"`(기본): 2층 몫(`share`)에 방향 가중(그 방향 출발 재차 합 ÷ 슬롯 전체 재차 합 —
    전부 NaN·0이면 방향 균등)을 곱해 슬롯의 모든 열차에서 재정규화한다. 승차·하차 모두 같은
    가중을 쓴다(RESOLUTION_LADDER §1.3 — 하차 몫은 승차 몫과 같은 규칙이 기본).
    `rule="load"`: 승차는 그 열차의 출발 재차, 하차는 도착 재차에 비례한다(슬롯 합이 0/NaN이면
    그 흐름만 `share` 가중으로 대체).

    반환은 `node_rows` + `boarding_train_est`·`alighting_train_est`(이름은 `flow_cols`에서
    `_30min_est`를 떼고 `out_suffix`를 붙여 만든다) + `flow_rule`. 슬롯 승하차가 NaN이거나 그
    슬롯이 `slot_flows`에 없으면 그 슬롯의 열차는 전부 NaN이다(채우지 않는다, 원칙 8).
    """
    if rule not in ("share", "load"):
        raise ValueError(f"알 수 없는 rule: {rule!r}")
    slot_key = ["date", "station_no", "time_slot_30min"]
    board_col, alight_col = flow_cols[0], flow_cols[1]
    board_out = _flow_out_name(board_col, out_suffix)
    alight_out = _flow_out_name(alight_col, out_suffix)

    out = node_rows.merge(slot_flows[[*slot_key, board_col, alight_col]], on=slot_key, how="left")

    dir_key = [*slot_key, "direction"]
    dep_sum_dir = out.groupby(dir_key, observed=True)["onboard_dep_est"].transform("sum")
    dep_sum_slot = out.groupby(slot_key, observed=True)["onboard_dep_est"].transform("sum")
    n_dirs = out.groupby(slot_key, observed=True)["direction"].transform("nunique")
    dep_sum_slot_safe = np.where(dep_sum_slot > 0, dep_sum_slot, 1.0)
    dir_weight = np.where(dep_sum_slot > 0, dep_sum_dir / dep_sum_slot_safe, 1.0 / n_dirs)

    out["_share_raw"] = out["share"].to_numpy(dtype=float) * dir_weight
    share_sum = out.groupby(slot_key, observed=True)["_share_raw"].transform("sum")
    share_sum_safe = np.where(share_sum > 0, share_sum, 1.0)
    share_weight = np.where(share_sum > 0, out["_share_raw"].to_numpy() / share_sum_safe, np.nan)
    out = out.drop(columns=["_share_raw"])

    if rule == "load":
        arr_sum_slot = out.groupby(slot_key, observed=True)["onboard_arr_est"].transform("sum")
        arr_sum_slot_safe = np.where(arr_sum_slot > 0, arr_sum_slot, 1.0)
        board_weight = np.where(
            dep_sum_slot > 0,
            out["onboard_dep_est"].to_numpy(dtype=float) / dep_sum_slot_safe,
            share_weight,
        )
        alight_weight = np.where(
            arr_sum_slot > 0,
            out["onboard_arr_est"].to_numpy(dtype=float) / arr_sum_slot_safe,
            share_weight,
        )
    else:
        board_weight = share_weight
        alight_weight = share_weight

    out[board_out] = out[board_col].to_numpy(dtype=float) * board_weight
    out[alight_out] = out[alight_col].to_numpy(dtype=float) * alight_weight
    out["flow_rule"] = rule
    return out


_ERF_VEC = np.vectorize(math.erf)


def _norm_cdf(z):
    """표준정규 누적분포. scipy 없이 `math.erf`로 계산한다(CI에 scipy 미보장 원칙)."""
    return 0.5 * (1.0 + _ERF_VEC(np.asarray(z, dtype=float) / math.sqrt(2.0)))


def platform_accumulation(
    tau_min,
    headway_min,
    board_est,
    *,
    mix_h0: float = MIX_H0_DEFAULT,
    mix_h1: float = MIX_H1_DEFAULT,
    jsb_alpha1: float = -1.0,
    jsb_alpha2: float = 1.0,
    jsb_shift_min: float = 0.0,
):
    """직전 열차 출발 후 τ(`tau_min`)분 시점의 승강장 대기 인원 추정(L6, 선택·미검증).

    `F(τ; h) = w(h)·clip(τ/h,0,1) + (1-w(h))·G(τ; h)`, `w`는 `arrival_mix_weight`(배차가 짧으면
    무작위 도착 → 선형 누적). `G`는 이동 구간 (jsb_shift_min, h) 위의 Johnson SB 누적분포로
    Luethi(2007) 사전값(α1=-1, α2=1)을 기본으로 쓴다 — "열차 직전에 승강장이 가장 붐빈다"는
    형태만 표시하는 용도라 서울 실측으로 검증되지 않았다(등급으로 바꾸지 않는다).
    scipy 없이 `math.erf` 기반으로 표준정규 CDF를 계산한다. 배열·스칼라 모두 넘파이 브로드캐스팅
    으로 받는다.
    """
    tau = np.asarray(tau_min, dtype=float)
    h = np.asarray(headway_min, dtype=float)
    board = np.asarray(board_est, dtype=float)
    if np.any(h <= 0):
        raise ValueError(f"headway_min은 0보다 커야 한다: {headway_min!r}")

    w = arrival_mix_weight(h, mix_h0, mix_h1)
    ramp = np.clip(tau / h, 0.0, 1.0)

    shift = float(jsb_shift_min)
    denom = h - shift
    use_ramp_for_g = denom <= 0  # shift >= h: G를 정의할 구간이 없어 선형 램프로 대체
    denom_safe = np.where(denom > 0, denom, 1.0)
    x = np.clip((tau - shift) / denom_safe, 0.0, 1.0)

    interior = (x > 0.0) & (x < 1.0)
    x_safe = np.where(interior, x, 0.5)
    logit = np.log(x_safe / (1.0 - x_safe))
    g = _norm_cdf(jsb_alpha1 + jsb_alpha2 * logit)
    g = np.where(x <= 0.0, 0.0, g)
    g = np.where(x >= 1.0, 1.0, g)
    g = np.where(use_ramp_for_g, ramp, g)

    f = w * ramp + (1.0 - w) * g
    return board * f
