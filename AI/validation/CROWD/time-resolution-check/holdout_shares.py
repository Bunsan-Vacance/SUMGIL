"""135번 — 1층(1시간→30분) 비중의 홀드아웃 검증.

배율표(스냅샷)로 만든 전반/후반 비중을 그대로 승하차에 쓰려면, 그 비중이 **적용 대상 밖에서도
성립**해야 한다. 스냅샷 자기 자신과 비교하는 것은 순환 논증이라(Notion "혼잡도 시간 해상도" 한계 1)
축을 갈라서 본다.

1. **요일유형 홀드아웃** — 평일 비중을 토요일·일요일에 그대로 적용했을 때 실제 토·일 비중과의 차이.
   운영에서는 요일유형별 비중을 따로 쓰므로 이 오차를 그대로 먹지는 않지만, "다른 축에서도 모양이
   유지되는가"의 상한 진단이 된다. 공휴일(휴일)은 1~8호선 스냅샷에 없어 일요일 비중을 쓰게 되는데
   그 차이도 여기서 대리 측정한다(토→일 차이로).
2. **역 간 산포** — 같은 시간대에서 역별 비중의 표준편차. 작을수록 역별 비중 대신 시간대 공통 비중을
   써도 되고, 크면 역별 비중이 필요하다는 뜻(Notion 측정: 러시 3.7~5.2%p).
3. **방향 간 차이** — 같은 역·시간대에서 내선/외선(상선/하선) 비중 차이. 승하차에는 방향이 없어 평균을
   쓰는데, 그 평균이 얼마나 뭉개는지.

전부 1~8호선(9호선은 승하차 패널이 2025~2026이라 별도). 결과는 표준 출력 + `--out` 마크다운.

실행:
    cd AI
    python validation/CROWD/time-resolution-check/holdout_shares.py [--out path.md]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(AI_ROOT), str(AI_ROOT / "validation" / "CROWD" / "baseline-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluate_final import to_markdown

from app.CROWD.pipeline.disaggregate import half_hour_shares

CALIBRATION = AI_ROOT / "data" / "CROWD" / "processed" / "crowd_congestion_calibration.parquet"
RUSH = ["07-08", "08-09", "18-19", "19-20"]


def late_share(shares: pd.DataFrame) -> pd.DataFrame:
    """1시간마다 후반(HH:30) 비중 한 값 — 두 슬롯이 있는 시간만."""
    s = shares[shares["time_slot_30min"].str.endswith(":30")]
    return s[["station_no", "day_type", "time_slot", "share"]].rename(columns={"share": "late"})


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    chunks: list[str] = []

    def emit(title: str, frame: pd.DataFrame) -> None:
        print(f"\n### {title}", flush=True)
        print(frame.to_string(index=False), flush=True)
        chunks.append(f"### {title}\n\n{to_markdown(frame)}\n")

    cal = pd.read_parquet(CALIBRATION)
    cal = cal[cal["line"] != "9호선"]
    shares = half_hour_shares(cal)
    late = late_share(shares).dropna()

    # 1. 요일유형 홀드아웃 — 평일 비중을 토·일에 적용
    wide = late.pivot_table(index=["station_no", "time_slot"], columns="day_type", values="late")
    rows = []
    for src, dst in (("평일", "토요일"), ("평일", "일요일"), ("토요일", "일요일")):
        d = (wide[src] - wide[dst]).dropna() * 100
        rush = d[d.index.get_level_values("time_slot").isin(RUSH)]
        rows.append(
            {
                "적용": f"{src} 비중 → {dst}",
                "n": len(d),
                "MAE_%p": round(float(d.abs().mean()), 2),
                "RMSE_%p": round(float(np.sqrt((d**2).mean())), 2),
                "러시_MAE_%p": round(float(rush.abs().mean()), 2),
                "5%p_초과_비율_%": round(float((d.abs() > 5).mean() * 100), 1),
            }
        )
    emit("1. 요일유형 홀드아웃 — 후반 30분 비중 차이", pd.DataFrame(rows))

    # 2. 역 간 산포 (요일유형별 · 시간대별)
    disp = (
        late.groupby(["day_type", "time_slot"], observed=True)["late"]
        .agg(
            평균=lambda s: round(s.mean() * 100, 1),
            표준편차=lambda s: round(s.std() * 100, 1),
            n="count",
        )
        .reset_index()
    )
    emit(
        "2. 역 간 산포 — 후반 비중(%) 평균·표준편차",
        disp[disp["day_type"] == "평일"].drop(columns="day_type"),
    )

    # 3. 방향 간 차이 — 같은 역·요일유형·시간대에서 두 방향 비중 차
    c = cal.dropna(subset=["ratio"]).copy()
    c["hour"] = c["time_slot"].map(
        lambda t: (
            "24~"
            if t.startswith("00")
            else ("~06" if t.startswith("05") else f"{int(t[:2]):02d}-{int(t[:2]) + 1:02d}")
        )
    )
    c = c[c["time_slot"].str.endswith(":30")]
    tot = cal.dropna(subset=["ratio"]).copy()
    tot["hour"] = tot["time_slot"].map(
        lambda t: (
            "24~"
            if t.startswith("00")
            else ("~06" if t.startswith("05") else f"{int(t[:2]):02d}-{int(t[:2]) + 1:02d}")
        )
    )
    tot = (
        tot.groupby(["station_no", "direction", "day_type", "hour"], observed=True)["ratio"]
        .sum()
        .rename("tot")
    )
    c = c.merge(tot.reset_index(), on=["station_no", "direction", "day_type", "hour"])
    c["late_dir"] = c["ratio"] / c["tot"]
    dir_wide = c.pivot_table(
        index=["station_no", "day_type", "hour"], columns="direction", values="late_dir"
    )
    pairs = []
    for a, b in (("상선", "하선"), ("내선", "외선")):
        if a in dir_wide and b in dir_wide:
            dd = (dir_wide[a] - dir_wide[b]).dropna() * 100
            pairs.append(
                {
                    "방향쌍": f"{a}-{b}",
                    "n": len(dd),
                    "MAE_%p": round(float(dd.abs().mean()), 2),
                    "5%p_초과_비율_%": round(float((dd.abs() > 5).mean() * 100), 1),
                }
            )
    emit("3. 방향 간 후반 비중 차이 — 방향 평균이 뭉개는 크기", pd.DataFrame(pairs))

    if args.out:
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"\n[저장] {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
