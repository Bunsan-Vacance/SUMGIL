"""베이스라인 모델 — 요일유형 × 역 × 시간대 평균 조회.

이게 이 프로젝트에서 이겨야 할 기준선이다. 학습이랄 게 없고 학습 구간의 평균을 표로 만들어
조회하는 게 전부인데, **네이버지도·카카오맵이 지금 하고 있는 것이 정확히 이것**이라
(혼잡도를 요일유형별 평균으로 표시만 함) 이걸 못 이기면 서비스의 차별화 근거가 없어진다.

기상·이벤트를 넣은 모델이 이 표보다 나은지가 87번(예측 알고리즘 후보 검증)의 핵심 질문이고,
그 판단 기준을 여기서 고정한다.

**조회 실패 처리**: 평가 구간에만 나타나는 (요일유형, 역, 시간대) 조합은 학습 구간에 값이
없다. 이때 조용히 전체 평균으로 채우면 베이스라인 성능이 실제보다 좋아 보인다 — 채우지 않고
결측으로 남긴 뒤 몇 건인지 보고한다(`predict`가 NaN을 그대로 돌려준다).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 디렉터리명에 하이픈이 있어(`baseline-check`, validation/README.md의 `<기능>-check/` 관례)
# 패키지가 될 수 없다. 상대 import가 불가능하므로 같은 폴더를 경로에 넣고 평범하게 가져온다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dataset import BASELINE_KEYS, TARGETS


class DayTypeLookupBaseline:
    """요일유형 × 역 × 시간대 평균을 외워두고 그대로 되돌려주는 모델."""

    def __init__(self, keys: list[str] | None = None, targets: list[str] | None = None) -> None:
        self.keys = keys or BASELINE_KEYS
        self.targets = targets or TARGETS
        self.table_: pd.DataFrame | None = None

    def fit(self, train: pd.DataFrame) -> DayTypeLookupBaseline:
        self.table_ = train.groupby(self.keys)[self.targets].mean().reset_index()
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.table_ is None:
            raise RuntimeError("fit()을 먼저 호출해야 한다.")
        merged = frame[self.keys].merge(self.table_, on=self.keys, how="left")
        return merged[self.targets]


def regression_metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    """RMSE·MAE·MAPE를 한 번에 낸다.

    MAPE는 실측이 0인 행에서 발산하므로 그런 행을 빼고 계산하고, 몇 건을 뺐는지도 같이
    돌려준다 — 심야 시간대는 승하차가 0인 역이 많아 이 비중이 작지 않다.
    """
    mask = actual.notna() & predicted.notna()
    a = actual[mask].to_numpy(dtype=float)
    p = predicted[mask].to_numpy(dtype=float)
    if len(a) == 0:
        return {"rmse": np.nan, "mae": np.nan, "mape": np.nan, "n": 0, "mape_n": 0}

    error = a - p
    nonzero = a != 0
    mape = float(np.mean(np.abs(error[nonzero] / a[nonzero])) * 100) if nonzero.any() else np.nan

    return {
        "rmse": float(np.sqrt(np.mean(error**2))),
        "mae": float(np.mean(np.abs(error))),
        "mape": mape,
        "n": len(a),
        "mape_n": int(nonzero.sum()),
    }


def evaluate(model: DayTypeLookupBaseline, test: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """평가 지표 표와 조회 실패 건수를 돌려준다."""
    predicted = model.predict(test)
    missing = int(predicted[model.targets[0]].isna().sum())

    rows = []
    for target in model.targets:
        metrics = regression_metrics(test[target], predicted[target])
        rows.append({"target": target, **metrics})
    return pd.DataFrame(rows), missing


def residuals(model: DayTypeLookupBaseline, frame: pd.DataFrame) -> pd.DataFrame:
    """실측 − 베이스라인. 기상·이벤트가 설명해야 할 몫이 바로 이것이다."""
    predicted = model.predict(frame)
    out = frame[["date", "station_no", "time_slot", "day_type"]].copy()
    for target in model.targets:
        out[f"{target}_actual"] = frame[target].to_numpy()
        out[f"{target}_pred"] = predicted[target].to_numpy()
        out[f"{target}_resid"] = out[f"{target}_actual"] - out[f"{target}_pred"]
    return out
