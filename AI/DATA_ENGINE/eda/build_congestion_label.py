"""승하차에서 날짜별 혼잡도(%) 라벨을 계산한다.

논문 「빅데이터 분석을 이용한 지하철 혼잡도 예측 및 추천시스템」이 제시한 재귀식을 따른다.

    재차인원(n) = 재차인원(n-1) + 승차(n) − 하차(n)
    혼잡도(n)   = 재차인원(n) / 정원 × 100

이 식이 필요한 이유는 우리가 가진 세 축이 한 테이블에 모이지 않기 때문이다. 승하차에는
날짜가 있지만 상/하선도 혼잡도 %도 없고, 실측 혼잡도 스냅샷에는 상/하선과 %가 있지만
날짜가 없다(요일구분 3개뿐). 재귀식은 승하차로부터 **날짜별 혼잡도**를 만들어내고, 노선을
따라 누적하는 방향이 곧 상/하선이라 두 빈칸을 동시에 메운다.
자세한 결정 근거는 Notion [CROWD] 혼잡도 / "혼잡도 타겟 정의 — 재차인원 재귀식 채택".

**방향 분해 — 이 스크립트의 가장 큰 가정.**
승하차는 "그 역에서 몇 명이 탔나"만 알려주고 그중 몇 명이 상행이고 하행인지는 말해주지
않는다. 그래서 승차·하차를 그대로 누적하면 방향별 재차인원이 아니라 두 방향의 **차이**가
나온다(상행 통과량 − 하행 통과량). 이걸 방향별로 쪼개려면 OD(출발-도착) 행렬이 필요한데
없으므로, 표준적인 1차 근사인 **비례 배분**을 쓴다:

    OD(i,j) ∝ 승차(i) × 하차(j)   (i ≠ j)

즉 "i에서 탄 사람은 각 역의 하차 규모에 비례해 흩어진다"고 본다. 실제 통행 패턴(출근은
도심 방향으로 쏠린다)을 반영하지 못하므로 **이 가정이 이 라벨의 정확도 상한을 정한다.**
반드시 실측 스냅샷과 대조해 검증할 것 — 그 전까지 이 산출물은 확정 라벨이 아니다.

**배차 미보정.** 승하차는 1시간 누적인데 공식 혼잡도는 "그 시간에 지나간 열차들의 평균"
이다. 1시간에 열차가 15대 지났으면 15로 나눠야 열차당 인원이 되는데 배차 데이터가 없다.
그래서 `congestion_raw_pct`는 실제보다 훨씬 큰 값이 나온다 — 정상이다. 실측 스냅샷에서
역·시간대별 변환 배율을 역산하는 것이 다음 단계이고, 그때까지 이 컬럼은 **상대 비교용**
이다(절대 수준을 국토부 4단계 임계치와 직접 비교하면 안 된다).

실행:
    cd AI
    python -m DATA_ENGINE.eda.build_congestion_label
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

AI_ROOT = Path(__file__).resolve().parents[2]
CONF_DIR = AI_ROOT / "DATA_ENGINE" / "conf"
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"

PANEL_NAME = "crowd_panel_2024_2025.parquet"
OUTPUT_NAME = "crowd_congestion_label_2024_2025.parquet"

# 누적 방향 → 실측 스냅샷의 방향 라벨.
#
# **역번호 오름차순은 `하선`이다.** 상선은 노선의 기점(번호가 작은 쪽, 대체로 도심) 방향을
# 뜻하므로 번호가 커지는 쪽으로 누적한 결과는 하선이다. 2026-09-09 실측 대조로 확인 —
# 처음에 반대로 라벨링했더니 상선 점유비 상관이 −0.80(부호가 정확히 뒤집힘)으로 나왔다.
# 7호선 중계역이 그 예다: 번호 증가 방향(온수·강남 쪽) 재차인원이 아침에 정점인데,
# 실측에서 아침에 붐비는 건 하선이고 상선(장암 방향)은 저녁에 정점이다.
#
# 2호선 순환선도 같은 방향으로 뒤집힌다 — 번호 증가(시청→을지로입구→…)가 외선순환이다.
ASCENDING, DESCENDING = "하선", "상선"
CIRCULAR_LABELS = {ASCENDING: "외선", DESCENDING: "내선"}


def load_capacity() -> dict:
    with (CONF_DIR / "train_capacity.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topology() -> list[dict]:
    with (CONF_DIR / "line_topology.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)["segments"]


def expand_stations(spec: list) -> list[int]:
    """`range: [a, b]` 표기를 역번호 목록으로 편다."""
    out: list[int] = []
    for item in spec:
        if isinstance(item, dict) and "range" in item:
            start, end = item["range"]
            out.extend(range(int(start), int(end) + 1))
        else:
            out.append(int(item))
    return out


def resolve_segments(topology: list[dict], available: set[int]) -> tuple[list[dict], pd.DataFrame]:
    """설정의 역 순서를 패널에 실제로 있는 역만 남겨 확정하고, 빠진 역을 인벤토리로 낸다.

    3호선 충무로·6호선 연신내처럼 물리적으로는 그 호선에 있지만 승하차가 다른 호선에
    계상된 역이 있다. 그 지점에서 재귀가 끊기므로 조용히 넘기지 않고 남긴다.
    """
    resolved: list[dict] = []
    gaps: list[dict] = []
    for seg in topology:
        wanted = expand_stations(seg["stations"])
        present = [s for s in wanted if s in available]
        missing = [s for s in wanted if s not in available]
        if missing:
            gaps.append({"line": seg["line"], "segment": seg["segment"], "missing": missing})
        resolved.append({**seg, "stations": present})
    return resolved, pd.DataFrame(gaps)


def directional_loads(boarding: np.ndarray, alighting: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """비례 배분 OD로 링크별 상행·하행 통과량을 구한다.

    `boarding`/`alighting`은 노선 순서대로 정렬된 1차원 배열이고, 반환값은 각 역을
    **출발한 직후** 링크의 통과량이다(실측 스냅샷의 `출발역` 기준과 맞춘다).

    OD(i,j) = 승차(i) × 하차(j) / (총하차 − 하차(i))  로 두면
    상행 통과량(n) = Σ_{i≤n} 승차(i) × [Σ_{j>n} 하차(j)] / (총하차 − 하차(i)) 이고,
    이는 누적합만으로 벡터화된다.
    """
    total_alight = alighting.sum()
    if total_alight <= 0:
        return np.zeros_like(boarding), np.zeros_like(boarding)

    # 자기 역으로는 가지 않으므로 분모에서 자기 하차를 뺀다. 한 역이 전체 하차를 독점하면
    # 분모가 0이 되니 그 경우만 막는다.
    denom = total_alight - alighting
    weight = np.divide(boarding, denom, out=np.zeros_like(boarding), where=denom > 0)

    cum_alight = np.cumsum(alighting)
    alight_after = total_alight - cum_alight  # n보다 뒤쪽 역들의 하차 합
    alight_before = cum_alight - alighting  # n보다 앞쪽 역들의 하차 합

    cum_weight = np.cumsum(weight)  # i ≤ n
    weight_after = cum_weight[-1] - cum_weight  # i > n

    up = cum_weight * alight_after
    down = weight_after * alight_before
    return up, down


def _segment_frame(panel: pd.DataFrame, seg: dict, capacity: dict) -> pd.DataFrame | None:
    """한 구간(segment)의 모든 (date, time_slot)에 대해 방향별 재차인원을 계산한다."""
    stations = seg["stations"]
    if len(stations) < 2:
        return None

    order = {s: i for i, s in enumerate(stations)}
    sub = panel[panel["station_no"].isin(stations)].copy()
    if sub.empty:
        return None
    sub["seq"] = sub["station_no"].map(order)
    sub = sub.sort_values(["date", "time_slot", "seq"])

    n = len(stations)
    # (date, time_slot) × 역 격자로 펴서 그룹마다 같은 길이의 배열을 얻는다.
    board = (
        sub.pivot_table(
            index=["date", "time_slot"], columns="seq", values="boarding", aggfunc="sum"
        )
        .reindex(columns=range(n))
        .fillna(0.0)
    )
    alight = (
        sub.pivot_table(
            index=["date", "time_slot"], columns="seq", values="alighting", aggfunc="sum"
        )
        .reindex(columns=range(n))
        .fillna(0.0)
    )

    b = board.to_numpy()
    a = alight.to_numpy()
    up = np.empty_like(b)
    down = np.empty_like(b)
    for i in range(b.shape[0]):
        up[i], down[i] = directional_loads(b[i], a[i])

    cars = seg.get("cars_per_train") or capacity["cars_per_train"][seg["line"]]
    train_capacity = cars * capacity["car_capacity"]

    idx = board.index
    records = []
    for label, load in ((ASCENDING, up), (DESCENDING, down)):
        direction = CIRCULAR_LABELS[label] if seg.get("circular") else label
        frame = pd.DataFrame(load, index=idx, columns=stations).stack().reset_index()
        frame.columns = ["date", "time_slot", "station_no", "onboard"]
        frame["direction"] = direction
        records.append(frame)

    out = pd.concat(records, ignore_index=True)
    out["line"] = seg["line"]
    out["segment"] = seg["segment"]
    out["train_capacity"] = train_capacity
    out["congestion_raw_pct"] = out["onboard"] / train_capacity * 100
    return out


def terminal_residual(labels: pd.DataFrame, topology: list[dict]) -> pd.DataFrame:
    """구간 종점에서 재차인원이 0에 얼마나 가까운지 — 누적 오차의 크기를 재는 진단.

    닫힌 구간이라면 마지막 역을 떠나는 열차는 비어 있어야 한다. 절단 구간(`truncated`)과
    순환선은 이 제약이 성립하지 않으므로 제외한다.
    """
    rows = []
    for seg in topology:
        if seg.get("truncated") or seg.get("circular") or len(seg["stations"]) < 2:
            continue
        last, first = seg["stations"][-1], seg["stations"][0]
        sel = labels[(labels["line"] == seg["line"]) & (labels["segment"] == seg["segment"])]
        peak = sel["onboard"].max()
        for direction, edge in ((ASCENDING, last), (DESCENDING, first)):
            tail = sel[(sel["direction"] == direction) & (sel["station_no"] == edge)]["onboard"]
            if tail.empty:
                continue
            rows.append(
                {
                    "line": seg["line"],
                    "segment": seg["segment"],
                    "direction": direction,
                    "종점": edge,
                    "종점_평균재차": round(float(tail.mean()), 1),
                    "구간_최대재차": round(float(peak), 1),
                    "잔차비율_%": (
                        round(float(tail.mean()) / float(peak) * 100, 2) if peak else None
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_labels() -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    panel = pd.read_parquet(
        CROWD_PROCESSED / PANEL_NAME,
        columns=["date", "station_no", "time_slot", "boarding", "alighting"],
    )
    panel[["boarding", "alighting"]] = panel[["boarding", "alighting"]].fillna(0.0)

    capacity = load_capacity()
    topology, gaps = resolve_segments(load_topology(), set(panel["station_no"].unique()))

    frames = [f for seg in topology if (f := _segment_frame(panel, seg, capacity)) is not None]
    labels = pd.concat(frames, ignore_index=True)
    return labels, gaps, topology


def save_labels(labels: pd.DataFrame) -> Path:
    CROWD_PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = CROWD_PROCESSED / OUTPUT_NAME
    labels.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    labels, gaps, topology = build_labels()

    if len(gaps):
        print("[안내] 설정에는 있으나 승하차 데이터에 없는 역 (그 지점에서 재귀가 끊긴다):")
        print(gaps.to_string(index=False))

    residual = terminal_residual(labels, topology)
    if len(residual):
        print("\n[진단] 종점 재차인원 — 0에 가까울수록 누적 오차가 작다:")
        print(residual.to_string(index=False))

    out_path = save_labels(labels)
    print(
        f"\n저장 완료: {out_path} ({len(labels):,}행, "
        f"역 {labels['station_no'].nunique()}개, 구간 {labels['segment'].nunique()}종, "
        f"방향 {sorted(labels['direction'].unique())})"
    )
    print(
        "[안내] congestion_raw_pct는 배차 미보정이라 절대 수준이 과대하다 — 상대 비교용. "
        "실측 스냅샷 대조로 변환 배율을 구하는 것이 다음 단계."
    )


if __name__ == "__main__":
    main()
