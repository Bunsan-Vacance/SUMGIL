"""재학습 주기(rolling window) 가설 검증 — "최근 데이터로 재학습하면 나아지는가"를
가정이 아니라 실측으로 확인한다.

A1 프로토타입에서 avg(2024-01~11 전체) vs 실측(2025-07)이 10~26대 차이났다. 근데 이 격차의
진짜 원인이 **①시간 경과(오래된 데이터라서)**인지 **②계절 불일치(1~11월 평균엔 겨울·봄·가을이
섞여 있어 여름 패턴을 못 담음)**인지 구분이 안 된 상태였다 — 이걸 구분해야 "최근 N개월
rolling"이 실제로 맞는 처방인지 알 수 있다.

3가지 후보를 같은 ground truth(2025-07 실측)에 비교한다:

    (a) 전체(2024-01~11) 평균   — 지금 서빙 중인 것, 계절 섞임 + 8개월 전 데이터
    (b) 2024-07만 평균          — "같은 달, 작년" 가설(계절만 맞춤, recency는 못 챙김)
    (c) 2024-09~11만 평균       — "최근 3개월" 가설(recency만 챙김, 계절은 다름·가을)

(a)보다 (b)나 (c)가 확실히 나으면 → 그 방향(계절 매칭 or 최근성)이 맞다는 근거가 됨.
셋 다 비슷하면 → 이 정도 표본으로는 구분이 안 된다는 뜻이니 추가 검증 필요.

실행:
    cd AI
    PYTHONPATH=. PYTHONIOENCODING=utf-8 python validation/BYC/lightgbm-stock-conversion-check/src/retrain_window_diagnosis.py
"""

from __future__ import annotations

import pandas as pd

from app.BIKE.pipeline.calendar import load_holidays
from app.BIKE.pipeline.dataset import monthly_paths
from app.BIKE.pipeline.lookup import StockProfileBaseline

CANDIDATES = {
    "(a) 2024-01~11 전체(지금 서빙 중)": monthly_paths("train", None),  # 11개월 전부
    "(b) 2024-07만(같은 달, 작년)": monthly_paths("train", ["202407"]),
    "(c) 2024-09~11만(최근 3개월)": monthly_paths("train", ["202409", "202410", "202411"]),
}


def main() -> None:
    holidays = load_holidays()

    print("[진단] ground truth(2025-07 실측) 계산...")
    gt = StockProfileBaseline().fit_streaming(monthly_paths("test", ["202507"]), holidays).table_
    gt = gt.rename(columns={"exp_bikes": "gt_exp_bikes"})[["od_station_id", "dow_type", "time_slot", "gt_exp_bikes"]]
    print(f"[진단] ground truth {len(gt):,}행")

    results = {}
    for name, paths in CANDIDATES.items():
        print(f"\n[진단] {name} ({len(paths)}개월) 계산 중...")
        cand = StockProfileBaseline().fit_streaming(paths, holidays).table_
        merged = cand.merge(gt, on=["od_station_id", "dow_type", "time_slot"], how="inner")
        merged["abs_err"] = (merged["exp_bikes"] - merged["gt_exp_bikes"]).abs()
        results[name] = merged
        print(f"  비교 가능 행수: {len(merged):,} / MAE: {merged['abs_err'].mean():.3f}")

    print("\n=== 요약 ===")
    summary = pd.DataFrame(
        {
            name: {"비교행수": len(df), "MAE": df["abs_err"].mean(), "중앙값 오차": df["abs_err"].median()}
            for name, df in results.items()
        }
    ).T
    print(summary.to_string())

    # ── station별로 (a)보다 (b)/(c)가 나은 비율도 확인 ──
    a_key, b_key, c_key = list(CANDIDATES.keys())
    a = results[a_key].set_index(["od_station_id", "dow_type", "time_slot"])["abs_err"]
    b = results[b_key].set_index(["od_station_id", "dow_type", "time_slot"])["abs_err"]
    c = results[c_key].set_index(["od_station_id", "dow_type", "time_slot"])["abs_err"]
    common = a.index.intersection(b.index).intersection(c.index)
    print(f"\n[진단] 셋 다 비교 가능한 (station,dow_type,time_slot) 조합: {len(common):,}개")
    print(f"  (b)가 (a)보다 나은 비율: {(b.loc[common] < a.loc[common]).mean():.1%}")
    print(f"  (c)가 (a)보다 나은 비율: {(c.loc[common] < a.loc[common]).mean():.1%}")


if __name__ == "__main__":
    main()
