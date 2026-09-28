"""lookup 베이스라인 — 요일유형 × 역 × 시간대 평균 조회.

87번(예측 알고리즘 후보 검증)이 세운 기준선이자, 최종 모델의 1단계다. 네이버지도·카카오맵이
지금 하고 있는 것이 정확히 이것(요일유형별 평균 표시)이라 이걸 못 이기면 서비스 차별화
근거가 없다. 트리 모델은 이 표를 재현하지 못하므로(범주형 직접 투입 시 −11~−47%) 최종
예측은 항상 `lookup 예측 + 잔차 모델 예측`으로 재구성한다 — `validation/CROWD/baseline-check/
features.py` docstring 참고.

`validation/CROWD/baseline-check/baseline.py`에서 승격했다. 검증 기록(디버깅 경위·실패
사례)은 거기 남기고 여기는 동작만 둔다.

**조회 실패 처리**: 학습 구간에 없는 (요일유형, 역, 시간대) 조합은 NaN으로 남긴다. 전체
평균으로 채우면 성능이 실제보다 좋아 보이고, 서빙에서는 "데이터 부족"으로 표시해야 한다
(데이터 검증 리포트 원칙 8).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

TARGETS = ["boarding", "alighting"]
BASELINE_KEYS = ["day_type", "station_no", "time_slot"]


class DayTypeLookupBaseline:
    """요일유형 × 역 × 시간대 평균을 외워두고 그대로 되돌려주는 모델."""

    def __init__(self, keys: list[str] | None = None, targets: list[str] | None = None) -> None:
        self.keys = list(keys or BASELINE_KEYS)
        self.targets = list(targets or TARGETS)
        self.table_: pd.DataFrame | None = None

    def fit(self, train: pd.DataFrame, weights: pd.Series | None = None) -> DayTypeLookupBaseline:
        """`weights=None`이면 지금과 같은 단순 평균, 주면 타깃별 가중 평균(227 연도 표본 가중).

        `weights`는 `train.index`에 맞춘 양수 Series로 본다. `.mean()`이 타깃별로 NaN을
        건너뛰듯, 타깃이 NaN인 행은 그 타깃의 분모(가중 합)에서도 뺀다 — 타깃마다 결측
        위치가 달라 가중을 한 번에 계산할 수 없다.
        """
        if weights is None:
            self.table_ = train.groupby(self.keys, observed=True)[self.targets].mean().reset_index()
            return self
        if len(weights) != len(train):
            raise ValueError(f"weights 길이({len(weights)})가 train 길이({len(train)})와 다르다.")
        w = np.asarray(weights, dtype="float64")
        if (w < 0).any():
            raise ValueError("weights에 음수가 있다 — 가중치는 전부 0 이상이어야 한다.")

        keys_frame = train[self.keys].reset_index(drop=True)
        by = [keys_frame[k] for k in self.keys]
        columns: dict[str, pd.Series] = {}
        for target in self.targets:
            values = train[target].to_numpy(dtype="float64")
            valid = ~np.isnan(values)
            wt = w * valid  # 타깃이 NaN인 행은 그 타깃 계산에서 가중을 0으로 뺀다
            wx = wt * np.where(valid, values, 0.0)
            numer = pd.Series(wx, index=keys_frame.index).groupby(by, observed=True).sum()
            denom = pd.Series(wt, index=keys_frame.index).groupby(by, observed=True).sum()
            with np.errstate(invalid="ignore", divide="ignore"):
                columns[target] = numer / denom  # 분모 0(그 그룹 전부 NaN)이면 NaN — 채우지 않는다
        table = pd.concat(columns, axis=1)
        self.table_ = table.reset_index()[[*self.keys, *self.targets]]
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.table_ is None:
            raise RuntimeError("fit()을 먼저 호출해야 한다.")
        merged = frame[self.keys].merge(self.table_, on=self.keys, how="left")
        return merged[self.targets]

    def residuals(self, frame: pd.DataFrame) -> pd.DataFrame:
        """`{target}_pred`·`{target}_resid`(실측 − 예측) 컬럼을 가진 프레임. 행 순서 보존."""
        pred = self.predict(frame)
        out = pd.DataFrame(index=frame.index)
        for t in self.targets:
            out[f"{t}_pred"] = pred[t].to_numpy()
            out[f"{t}_resid"] = frame[t].to_numpy() - pred[t].to_numpy()
        return out

    # ── 아티팩트 ──
    def save(self, path: Path) -> Path:
        if self.table_ is None:
            raise RuntimeError("fit()을 먼저 호출해야 한다.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.table_.to_parquet(path, index=False)
        return path

    @classmethod
    def load(cls, path: Path, keys: list[str] | None = None, targets: list[str] | None = None):
        model = cls(keys, targets)
        model.table_ = pd.read_parquet(path)
        return model
