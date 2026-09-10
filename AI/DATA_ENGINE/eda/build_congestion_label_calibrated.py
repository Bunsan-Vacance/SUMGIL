"""7번(`build_congestion_calibration.py`)의 배율표를 재귀식 혼잡도에 적용해 **30분·보정
혼잡도** 라벨을 만든다 → `crowd_congestion_label_calibrated_2024_2026.parquet`.

    보정_혼잡도(날짜, 역, 방향, 30분)
      = congestion_raw_pct(날짜, 역, 방향, 그 30분이 속한 1시간)
      × 배율(역, 방향, 요일유형, 30분)

`build_congestion_label.py`의 재귀식 결과는 **1시간 20슬롯·날짜별**(배차 미보정, 배차
10배 과대)이고, 배율표는 **30분 39슬롯·요일유형별**(날짜 축 없음, 스냅샷 대조로 낸 정적
비율)이다. 재귀식 각 행을 그 시간에 속하는 30분 슬롯 1~2개로 펼친 뒤(`~06`은 05:30
하나뿐, 나머지는 HH:00·HH:30 둘) 배율을 곱하면 두 축이 합쳐진다 — 날짜별 변동은 재귀식
에서, 배차 보정과 30분 내 분포 모양은 배율표에서 가져오는 구조다.

**날짜별 재귀식 결과의 평균을 요일유형별로 다시 잡으면 정의상 스냅샷 실측과 같아져야
한다** — 배율 자체가 `실측 ÷ mean(raw)`로 정의됐기 때문이다. 이 항등식을 `main()`이
자체 검증으로 출력한다(질량 보존 검증과 같은 성격).

**배율이 없는 조합은 결측으로 남긴다.** 7번에서 이미 확인한 잔여 결측(2호선 지선 방향
라벨 불일치, 결번 역, 요일유형 미대응)이 여기서도 그대로 결측으로 전파된다 — 값을
추정해 채우지 않는다(원칙 1).

실행:
    cd AI
    python -m DATA_ENGINE.eda.build_congestion_label_calibrated
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from DATA_ENGINE.eda.build_congestion_calibration import bucket_day_type
from DATA_ENGINE.eda.build_crowd_panel import attach_calendar

AI_ROOT = Path(__file__).resolve().parents[2]
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"

LABEL_NAME = "crowd_congestion_label_2024_2026.parquet"
CALIBRATION_NAME = "crowd_congestion_calibration.parquet"
OUTPUT_NAME = "crowd_congestion_label_calibrated_2024_2026.parquet"


def hour_bucket_to_30min_slots(hour_bucket: str) -> list[str]:
    """재귀식 20슬롯 라벨을 그 안에 속한 30분 슬롯 목록으로 편다.

    `build_congestion_calibration.slot_30min_to_hour_bucket`의 역함수다. `~06`은 스냅샷의
    첫 슬롯이 05:30 하나뿐이라(첫차 준비 구간, 05:00 이전은 서비스 공백이라 스냅샷 자체가
    조사하지 않는다) 1개, 나머지는 HH:00·HH:30 2개로 나뉜다.
    """
    if hour_bucket == "24~":
        return ["00:00", "00:30"]
    if hour_bucket == "~06":
        return ["05:30"]
    hour = int(hour_bucket.split("-")[0])
    return [f"{hour:02d}:00", f"{hour:02d}:30"]


def explode_to_30min(labels: pd.DataFrame) -> pd.DataFrame:
    """재귀식 라벨의 각 행(1시간)을 그 안의 30분 슬롯 1~2개로 복제해 펼친다.

    복제된 행은 `congestion_raw_pct`·`onboard` 등 1시간 값을 그대로 물려받는다 — 30분
    단위로 다시 계산하는 게 아니라, 같은 1시간 안의 두 30분에 (전반·후반) 서로 다른 배율을
    곱해서 분해하는 구조이기 때문이다.
    """
    out = labels.copy()
    out["time_slot_30min"] = out["time_slot"].map(hour_bucket_to_30min_slots)
    return out.explode("time_slot_30min", ignore_index=True)


def apply_calibration(labels: pd.DataFrame, calibration: pd.DataFrame) -> pd.DataFrame:
    """30분 단위로 펼친 재귀식 라벨에 배율을 곱해 보정 혼잡도를 낸다."""
    frame = attach_calendar(labels.copy())
    frame["day_type_bucket"] = bucket_day_type(frame["line"], frame["day_type"])
    frame = explode_to_30min(frame)

    ratio_key = calibration[["station_no", "direction", "day_type", "time_slot", "ratio"]].rename(
        columns={"day_type": "day_type_bucket", "time_slot": "time_slot_30min"}
    )

    merged = frame.merge(
        ratio_key, on=["station_no", "direction", "day_type_bucket", "time_slot_30min"], how="left"
    )
    merged["congestion_pct_calibrated"] = merged["congestion_raw_pct"] * merged["ratio"]
    return merged


def verify_calibration_identity(
    calibrated: pd.DataFrame, calibration: pd.DataFrame
) -> pd.DataFrame:
    """요일유형별로 평균을 다시 잡으면 배율표(=스냅샷 실측)와 같아지는지 확인한다.

    배율이 `실측 ÷ mean(raw)`로 정의됐으니, `mean(raw) × 배율`의 평균은 정의상 실측과
    같아야 한다 — 다른 값이 나오면 조인 키가 잘못됐다는 뜻이다. 차이가 있는 행만 돌려준다.
    """
    key = ["station_no", "direction", "day_type_bucket", "time_slot_30min"]
    recomputed = (
        calibrated.dropna(subset=["congestion_pct_calibrated"])
        .groupby(key, observed=True)["congestion_pct_calibrated"]
        .mean()
        .rename("recomputed_mean")
        .reset_index()
    )
    reference = calibration.rename(
        columns={"day_type": "day_type_bucket", "time_slot": "time_slot_30min"}
    )[[*key, "congestion_pct"]]
    compared = recomputed.merge(reference, on=key, how="inner")
    mismatch = (compared["recomputed_mean"] - compared["congestion_pct"]).abs() > 1e-6
    return compared[mismatch]


def build_calibrated_label() -> tuple[pd.DataFrame, pd.DataFrame]:
    labels = pd.read_parquet(CROWD_PROCESSED / LABEL_NAME)
    calibration = pd.read_parquet(CROWD_PROCESSED / CALIBRATION_NAME)

    calibrated = apply_calibration(labels, calibration)
    identity_mismatch = verify_calibration_identity(calibrated, calibration)

    cols = [
        "date",
        "station_no",
        "line",
        "segment",
        "direction",
        "time_slot_30min",
        "onboard",
        "train_capacity",
        "congestion_raw_pct",
        "ratio",
        "congestion_pct_calibrated",
    ]
    return calibrated[cols].rename(columns={"time_slot_30min": "time_slot"}), identity_mismatch


def save_calibrated_label(calibrated: pd.DataFrame) -> Path:
    CROWD_PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = CROWD_PROCESSED / OUTPUT_NAME
    calibrated.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    calibrated, identity_mismatch = build_calibrated_label()
    out_path = save_calibrated_label(calibrated)

    total = len(calibrated)
    missing = int(calibrated["congestion_pct_calibrated"].isna().sum())
    print(
        f"[안내] 전체 {total:,}행 중 배율 미매칭으로 보정값이 결측인 행 {missing:,}행 "
        f"({missing / total * 100:.1f}%) — 7번에서 확인한 잔여 결측이 그대로 전파된 것이다."
    )
    if len(identity_mismatch):
        print(f"[경고] 항등식(요일유형 평균 재계산=배율표 실측) 불일치 {len(identity_mismatch)}건:")
        print(identity_mismatch.to_string(index=False))
    else:
        print("[확인] 요일유형별 평균 재계산이 배율표의 실측값과 일치 — 항등식 통과.")

    print(
        f"\n저장 완료: {out_path} ({len(calibrated):,}행, "
        f"{calibrated['date'].min():%Y-%m-%d}~{calibrated['date'].max():%Y-%m-%d})"
    )


if __name__ == "__main__":
    main()
