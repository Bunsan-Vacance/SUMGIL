"""시뮬레이션 정답 생성기 — 30분 방향별 라벨을 열차 단위 "그날의 실제"로 내리는 확률 과정. 순수 함수(92번).

날짜별 30분 이하 실측은 어느 공개 원천에도 없다. 그래서 열차·5분 단위 예측을 평가할 정답을 **가정을 밝힌
시뮬레이션**으로 만든다. 핵심은 생성기가 예측기와 같은 규칙으로 값을 만들면 평가가 순환한다는 점이다 —
생성기에는 예측기가 **모르는 변동** 세 가지를 반드시 넣고, 그 크기는 민감도 표로 함께 낸다
(Notion "모델 입력·검증 라벨·비교군 설계 전략" 3.2절).

| 층 | 예측기가 아는 것 | 생성기가 더하는 것(= 평가 대상) | 파라미터 |
| --- | --- | --- | --- |
| 30분 총량 | 88 라벨(실측 승하차 기반) | 없음 — 슬롯 총량은 라벨로 고정 | — |
| 시간 안 모양 | 슬롯 안 균등(간격 비례) | 그날·그 역의 기울기 편차 ε ~ N(0, σ_shape): 전반/후반 열차 몫이 (1 ± ε) | `sigma_shape` |
| 도착 과정 | 배차 의존 혼합 기대값 | Poisson 표본(열차별 재차인원이 기대값 주위에서 흔들림) | `poisson` |
| 운행 편차 | 계획 시각표 | 러시 열차 일부 지연(간격 ×1.5) / 결행 — 실제 도착 시각으로 재배분 | `scenario`, `p_delay`, `p_skip` |
| 재차·혼잡도 | 같은 정원 | 열차별 재차 ÷ 정원 | — |

**가정(정직하게 적어두는 것).** (1) 30분 슬롯의 방향별 재차인원 총량은 88 라벨이 맞다고 본다 — 이 층의 오차
(재귀식 누적, 배율표)는 여기서 평가하지 않는다. (2) 열차별 재차는 "슬롯 총량의 배분"으로 만들며 승차·하차를
따로 흘리지 않는다 — 88 라벨이 이미 역을 떠나는 구간의 재차인원이라서다. (3) 운행 편차는 계획 시각표를
흔든 것이고 실제 운행 기록이 아니다. 따라서 결과 수치는 실측 대비 정확도가 아니라 **"이 가정 위에서의
일관성이며, 실측이 있었다면 틀렸을 정도의 하한"**이다(원칙 4).

사용: `simulate(slot_loads, timetable, SimConfig(...), seed)` → 열차 한 대 = 한 행. 같은 seed면 같은 결과.
입력 준비(라벨·시각표 읽기)는 `DATA_ENGINE/eda/build_sim_truth.py`가 한다 — `app/`은 `DATA_ENGINE/`을
import하지 않는다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from app.CROWD.pipeline.disaggregate import (
    LONG_HEADWAY_MIN,
    MIX_H0_DEFAULT,
    MIX_H1_DEFAULT,
    SLOT_MINUTES,
    _minutes_to_slot30,
    _to_minutes,
    arrival_mix_weight,
)

RUSH_SLOTS = {"07:30", "08:00", "08:30", "18:00", "18:30", "19:00"}
SCENARIOS = ("none", "delay", "skip")
TRAIN_KEY = ["station_no", "direction", "day_type"]
SLOT_KEY = [*TRAIN_KEY, "time_slot_30min"]


@dataclass(frozen=True)
class SimConfig:
    """생성기 가정 한 벌. 민감도 격자는 이 값들을 바꿔 여러 벌 돌린다."""

    sigma_shape: float = 0.05  # 슬롯 안 기울기 편차 σ (135 홀드아웃 3~5%p 근거)
    mix_h0: float = MIX_H0_DEFAULT  # 도착 혼합: 이 분까지 무작위 도착 가중 1
    mix_h1: float = MIX_H1_DEFAULT  # 이 분부터 무작위 도착 가중 0
    poisson: bool = True  # 열차별 재차를 Poisson 표본으로(False면 기대값 그대로)
    scenario: str = "none"  # none / delay / skip
    p_delay: float = 0.2  # delay: 러시 열차 중 지연되는 비율
    delay_factor: float = 0.5  # delay: 지연 = 직전 간격 × factor (간격 ×1.5)
    p_skip: float = 0.05  # skip: 러시 열차 중 결행 비율

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError(f"scenario는 {SCENARIOS} 중 하나: {self.scenario}")
        if self.sigma_shape < 0:
            raise ValueError("sigma_shape는 0 이상")

    def tag(self) -> str:
        return f"{self.scenario}_s{self.sigma_shape:g}_h{self.mix_h0:g}-{self.mix_h1:g}"


# ── 운행 편차 ──
def perturb_timetable(
    timetable: pd.DataFrame, cfg: SimConfig, rng: np.random.Generator
) -> pd.DataFrame:
    """계획 시각표 → 그날의 실제 시각표. `arr_min_true`, `delayed`, (결행 열차는 행 제거).

    delay: 러시 슬롯 열차 중 p_delay 비율을 직전 간격 × delay_factor 만큼 늦춘다(간격 ×1.5).
           늦춘 열차는 다음 열차와 붙는다(bunching) — 재정렬 후 간격을 다시 계산한다.
    skip:  러시 슬롯 열차 중 p_skip 비율을 뺀다. 그 열차 몫은 슬롯 안 나머지 열차가 받는다.
    """
    tt = timetable.copy()
    tt["arr_min_plan"] = _to_minutes(tt["arrival_time"])
    tt = tt.sort_values([*TRAIN_KEY, "arr_min_plan"]).reset_index(drop=True)
    tt["headway_plan"] = (
        tt.groupby(TRAIN_KEY, observed=True)["arr_min_plan"].diff().fillna(float(SLOT_MINUTES))
    )
    slot_plan = ((tt["arr_min_plan"] // SLOT_MINUTES) * SLOT_MINUTES).map(_minutes_to_slot30)
    # 첫차는 직전 간격이 없어(기본 30분) 지연 크기를 정할 수 없다 → 편차 대상에서 뺀다
    has_prev = (tt.groupby(TRAIN_KEY, observed=True).cumcount() > 0).to_numpy()
    rush = slot_plan.isin(RUSH_SLOTS).to_numpy() & has_prev
    n = len(tt)
    tt["arr_min_true"] = tt["arr_min_plan"].astype(float)
    tt["delayed"] = False
    tt["skipped"] = False
    if cfg.scenario == "delay":
        hit = rush & (rng.random(n) < cfg.p_delay)
        tt.loc[hit, "arr_min_true"] += tt.loc[hit, "headway_plan"] * cfg.delay_factor
        tt.loc[hit, "delayed"] = True
    elif cfg.scenario == "skip":
        hit = rush & (rng.random(n) < cfg.p_skip)
        tt.loc[hit, "skipped"] = True
        tt = tt[~tt["skipped"]].reset_index(drop=True)
    tt = tt.sort_values([*TRAIN_KEY, "arr_min_true"]).reset_index(drop=True)
    tt["headway_true"] = (
        tt.groupby(TRAIN_KEY, observed=True)["arr_min_true"].diff().fillna(float(SLOT_MINUTES))
    )
    tt["time_slot_30min"] = ((tt["arr_min_true"] // SLOT_MINUTES) * SLOT_MINUTES).map(
        _minutes_to_slot30
    )
    return tt


# ── 배분 + 변동 ──
def simulate(
    slot_loads: pd.DataFrame,
    timetable: pd.DataFrame,
    cfg: SimConfig | None = None,
    seed: int = 0,
    load_col: str = "onboard_30min_est",
) -> pd.DataFrame:
    """30분 슬롯 재차인원을 "그날의 실제" 열차별 재차인원으로 내린다.

    `slot_loads`: date, station_no, direction, day_type, time_slot_30min, train_capacity, `load_col`
                  (+ line 등 그대로 전달). `timetable`: station_no, direction, day_type, train_id,
                  arrival_time. 반환: 열차 한 대 = 한 행, `onboard_true`, `congestion_true`,
                  `arrival_time_true`, `headway_true`, `delayed`, `mix_w`, `shape_mult`, `seed`.
    같은 (입력, cfg, seed)면 결과가 같다. 슬롯에 열차가 없으면 그 슬롯은 나오지 않는다.
    """
    cfg = cfg or SimConfig()
    rng = np.random.default_rng(seed)
    tt = perturb_timetable(timetable, cfg, rng)

    grp = tt.groupby(SLOT_KEY, observed=True)
    share_prop = tt["headway_true"] / grp["headway_true"].transform("sum")
    w = arrival_mix_weight(tt["headway_true"].to_numpy(), cfg.mix_h0, cfg.mix_h1)
    n_slot = grp["train_id"].transform("count").to_numpy()
    tt["share"] = w * share_prop.to_numpy() + (1.0 - w) / n_slot
    tt["mix_w"] = w
    # 슬롯 안 위치(-1 전반 끝 … +1 후반 끝) — 모양 편차는 이 축을 따라 기울어진다
    slot_start = (tt["arr_min_true"] // SLOT_MINUTES) * SLOT_MINUTES
    tt["pos"] = ((tt["arr_min_true"] - slot_start) - SLOT_MINUTES / 2) / (SLOT_MINUTES / 2)
    tt["headway_long"] = tt["headway_true"] > LONG_HEADWAY_MIN

    cols = [
        *SLOT_KEY,
        "train_id",
        "arrival_time",
        "arr_min_true",
        "headway_plan",
        "headway_true",
        "headway_long",
        "delayed",
        "share",
        "mix_w",
        "pos",
    ]
    m = slot_loads.merge(tt[cols], on=SLOT_KEY, how="inner")
    if m.empty:
        return m.assign(onboard_true=[], congestion_true=[])

    # 그날·그 역·그 슬롯의 모양 편차 ε: 같은 (date, 슬롯 키) 안에서는 하나의 ε
    cell = m.groupby(["date", *SLOT_KEY], observed=True, sort=False).ngroup().to_numpy()
    eps_cell = (
        rng.normal(0.0, cfg.sigma_shape, size=cell.max() + 1) if cfg.sigma_shape > 0 else None
    )
    mult = 1.0 + (eps_cell[cell] * m["pos"].to_numpy() if eps_cell is not None else 0.0)
    m["shape_mult"] = np.clip(mult, 0.2, None)
    raw = m["share"].to_numpy() * m["shape_mult"].to_numpy()
    m["share_true"] = raw / pd.Series(raw).groupby(cell).transform("sum").to_numpy()
    expected = m[load_col].to_numpy() * m["share_true"].to_numpy()
    m["onboard_true"] = rng.poisson(expected).astype(float) if cfg.poisson else expected
    m["congestion_true"] = m["onboard_true"] / m["train_capacity"] * 100.0
    m["arrival_time_true"] = (m["arr_min_true"] % (24 * 60)).map(
        lambda x: f"{int(x) // 60:02d}:{int(x) % 60:02d}"
    )
    m["seed"] = seed
    for k, v in asdict(cfg).items():
        m[f"cfg_{k}"] = v
    return (
        m.drop(columns=["pos"])
        .sort_values(["date", *SLOT_KEY, "arr_min_true"])
        .reset_index(drop=True)
    )


def bin5_of(arr_min: pd.Series) -> pd.Series:
    """도착 시각(운행일 분) → 5분 빈 시작 'HH:MM'."""
    return ((arr_min // 5) * 5 % (24 * 60)).map(lambda x: f"{int(x) // 60:02d}:{int(x) % 60:02d}")
