"""아티팩트 로딩 → 예측 재구성(`lookup + 잔차 모델`).

`train.py`가 저장한 디렉터리 하나를 읽어, 패널 형태의 입력(날짜·역·시간대·요일유형·이벤트
컬럼, 파생 전)에 대해 승차·하차 예측을 낸다. 파생은 학습과 **같은 함수**로 만든다 — 그래서
입력 프레임에는 시차 계산에 필요한 과거 행(전날·1주 전)이 함께 들어와야 한다. 배치 추론에서는
"대상 날짜 + 직전 7일"을 넘기고 대상 날짜 행만 잘라 쓴다.

**서빙 시점의 결측.** D−1 원천만 있으면 대상 날짜의 같은 시각 이웃·직전 슬롯 컬럼은 NaN이다
(그 시각 실측이 아직 없다). 결측을 채우지 않고 그대로 모델에 준다 — LightGBM은 NaN을 분할
정보로 다루며, 마스킹 평가(`validation/.../evaluate_final.py`)가 이 상황의 성능을 잰다.
lookup 조회 실패(학습 구간에 없는 요일유형×역×시간대)는 NaN으로 남겨 "데이터 부족"으로 노출한다.

실행:
    cd AI
    python -m app.CROWD.pipeline.predict --artifact models/CROWD/<dir> --date 2025-06-02
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.dataset import load_panel, resolved_segments
from app.CROWD.pipeline.features import add_derived_columns, build_matrix
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline


class CrowdPredictor:
    """아티팩트 디렉터리 하나 = 예측기 하나."""

    def __init__(self, artifact_dir: Path) -> None:
        self.dir = Path(artifact_dir)
        self.meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        self.lookup = DayTypeLookupBaseline.load(
            self.dir / "lookup.parquet", keys=self.meta["lookup_keys"], targets=self.meta["targets"]
        )
        self.feature_set: str = self.meta["feature_set"]
        self.group_col: str | None = self.meta.get("group_col")
        self._boosters: dict[str, dict[str, object]] = {}
        from lightgbm import Booster

        for target, by_group in self.meta["model_files"].items():
            self._boosters[target] = {
                gkey: Booster(model_file=str(self.dir / name)) for gkey, name in by_group.items()
            }

    def predict_derived(self, derived: pd.DataFrame) -> pd.DataFrame:
        """이미 파생이 붙은 프레임에 대해 예측. 반환: date·station_no·time_slot + 타깃별 pred·lookup."""
        X = build_matrix(derived, self.feature_set)
        lookup_pred = self.lookup.predict(derived)
        out = derived[["date", "station_no", "time_slot"]].copy()
        for target in self.meta["targets"]:
            resid_pred = np.full(len(derived), np.nan)
            by_group = self._boosters[target]
            if self.group_col is None:
                resid_pred[:] = by_group["__all__"].predict(X)
            else:
                keys = derived[self.group_col].astype(str).to_numpy()
                for gkey, booster in by_group.items():
                    mask = keys == gkey
                    if mask.any():
                        resid_pred[mask] = booster.predict(X[mask])
            out[f"{target}_lookup"] = lookup_pred[target].to_numpy()
            out[f"{target}_pred"] = lookup_pred[target].to_numpy() + resid_pred
        return out

    def predict(self, panel: pd.DataFrame, segments: list[dict]) -> pd.DataFrame:
        """파생 전 패널(대상 날짜 + 시차용 과거 행)을 받아 파생을 붙이고 예측한다."""
        derived = add_derived_columns(panel, self.lookup, segments)
        return self.predict_derived(derived)


def predict_for_date(
    predictor: CrowdPredictor, panel: pd.DataFrame, target_date: pd.Timestamp, history_days: int = 7
) -> pd.DataFrame:
    """`panel`에서 대상 날짜와 직전 `history_days`일을 잘라 파생·예측하고 대상 날짜 행만 돌려준다."""
    target_date = pd.Timestamp(target_date)
    window = panel[
        (panel["date"] >= target_date - pd.Timedelta(days=history_days))
        & (panel["date"] <= target_date)
    ].reset_index(drop=True)
    segments, _ = resolved_segments(window)
    pred = predictor.predict(window, segments)
    return pred[pred["date"] == target_date].reset_index(drop=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--artifact", required=True, help="models/CROWD/<dir>")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD (패널에 있는 날짜)")
    ap.add_argument("--out", default=None, help="저장할 parquet 경로(생략 시 표준 출력에 요약)")
    args = ap.parse_args(argv)

    predictor = CrowdPredictor(args.artifact)
    panel = load_panel(with_events=True)
    pred = predict_for_date(predictor, panel, pd.Timestamp(args.date))
    if args.out:
        pred.to_parquet(args.out, index=False)
        print(f"[예측] 저장: {args.out} ({len(pred):,}행)")
    else:
        print(pred.head(20).to_string(index=False))
        for t in TARGETS:
            print(
                f"{t}: 예측 평균 {pred[f'{t}_pred'].mean():.1f}, lookup 결측 {pred[f'{t}_lookup'].isna().sum()}건"
            )


if __name__ == "__main__":
    main(sys.argv[1:])
