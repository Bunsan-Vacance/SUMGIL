"""후보 모델 레지스트리 — 87번(예측 알고리즘 후보 검증)이 비교할 세 후보.

무거운 의존성(lightgbm·xgboost·sklearn)은 함수 내부에서 지연 import한다
(`validation/README.md` 관례) — 이 모듈을 import하는 것만으로 세 라이브러리를 전부 로드하지
않기 위해서다.

세 모델은 범주형(day_type·station_no·time_slot) 처리 방식이 갈린다:
- LightGBM: `category` dtype을 그대로 받아 원-핫 없이 분할한다.
- XGBoost(2.0+): `enable_categorical=True` + `tree_method="hist"`면 마찬가지로 그대로 받는다.
- RandomForest(sklearn)는 category dtype을 못 받는다 — `.cat.codes`로 정수 인코딩해야 한다.
  트리 분할 기준으로는 순서가 의미 없어 순수 서수 인코딩으로도 충분하다.
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
    return X


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
