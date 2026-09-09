"""후보 모델 레지스트리 — 87번(예측 알고리즘 후보 검증)이 비교할 세 후보.

무거운 의존성(lightgbm·xgboost·sklearn)은 함수 내부에서 지연 import한다
(`validation/README.md` 관례) — 이 모듈을 import하는 것만으로 세 라이브러리를 전부 로드하지
않기 위해서다.

세 모델은 범주형(day_type·station_no·time_slot)과 결측(`game_attendance`) 처리 방식이
갈린다:
- LightGBM·XGBoost(2.0+, `enable_categorical=True`): `category` dtype과 NaN을 그대로 받아
  분할 기준의 일부로 쓴다 — "관중수 결측(경기 없음/관중수만 모름)"도 분할 정보가 된다.
- RandomForest(sklearn)는 `category` dtype도 NaN도 못 받는다. `.cat.codes`로 정수
  인코딩하고(순서는 의미 없어 서수 인코딩으로 충분), NaN은 0으로 채운다 — "경기 없음"과
  "경기는 있었는데 관중수를 모름"이 둘 다 0이 되어 구분이 사라지지만, 그 구분은
  `game_attendance_missing` 컬럼이 따로 담당하므로 정보 손실은 아니다.
"""

from __future__ import annotations

import pandas as pd

CANDIDATES = ["lightgbm", "random_forest", "xgboost"]


def _encode_for_model(X: pd.DataFrame, name: str) -> pd.DataFrame:
    if name != "random_forest":
        return X
    X = X.copy()
    for col in X.select_dtypes("category").columns:
        X[col] = X[col].cat.codes
    return X.fillna(0)


def build_model(name: str, random_state: int = 42):
    if name == "lightgbm":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            n_estimators=300,
            num_leaves=63,
            learning_rate=0.05,
            random_state=random_state,
            n_jobs=-1,
            verbose=-1,
        )
    if name == "random_forest":
        from sklearn.ensemble import RandomForestRegressor

        return RandomForestRegressor(
            n_estimators=200,
            max_depth=16,
            n_jobs=-1,
            random_state=random_state,
        )
    if name == "xgboost":
        from xgboost import XGBRegressor

        return XGBRegressor(
            n_estimators=300,
            max_depth=8,
            learning_rate=0.05,
            tree_method="hist",
            enable_categorical=True,
            random_state=random_state,
            n_jobs=-1,
        )
    raise ValueError(f"알 수 없는 후보: {name} (가능: {CANDIDATES})")


def fit_predict(
    name: str, X_train: pd.DataFrame, y_train: pd.Series, X_test: pd.DataFrame
) -> pd.Series:
    """`name` 후보를 학습해 `X_test`에 대한 예측을 돌려준다."""
    model = build_model(name)
    model.fit(_encode_for_model(X_train, name), y_train)
    predicted = model.predict(_encode_for_model(X_test, name))
    return pd.Series(predicted, index=X_test.index)
