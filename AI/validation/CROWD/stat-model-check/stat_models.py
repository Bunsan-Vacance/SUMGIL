"""145 — 통계 모형 비교 검증의 순수 로직: 계절 나이브 · OLS-AR · SARIMAX 1단계 앞 예측.

## 왜

배포 모델(`lookup + LightGBM(전날·같은요일유형직전·1주전 잔차 시차 + 이벤트 + 범주)`)은 "잔차에 AR
항을 건 모델"의 비선형 판이다. 이 모듈은 그 가설을 재는 데 필요한 계열을 순수 함수로 둔다 —
parquet·아티팩트 I/O는 `predict_all.py`가 맡고, 여기는 배열·시리즈만 받는다(테스트하기 쉽게).

- `attach_snaive` — 계절 나이브(H1): 같은 (역, 시간대)의 `day_lag`일 전 **원본값**. `lags.attach_day_lags`
  를 그대로 쓴다(위치 shift가 아니라 날짜·슬롯 키 조인이라 빠진 날은 NaN).
- `fit_ols` / `predict_ols` — 잔차 = 절편 + 시차 3종의 선형회귀(H3). `numpy.linalg.lstsq`로 유효
  (모두 유한한) 행만 적합하고, 유효 행이 부족하면 `None`을 돌려줘 그 시리즈를 NaN으로 둔다(원칙 8).
- `fit_predict_sarimax` — (역, 시간대, 타깃) 시리즈 하나에 SARIMAX를 2024 구간으로 적합하고
  **refit 없이**(`res.apply(..., refit=False)`) 전체 시리즈에 적용해 `forecast_start`부터의
  1단계 앞(`dynamic=False`) 예측을 낸다. 수렴 실패·예외는 개수로만 남기고 해당 시리즈는 NaN.
- `build_wide_series` / `run_sarima_batch` — 10,920개 시리즈를 시리즈마다 따로 조인하지 않고 pivot
  한 번으로 잘라 쓰기 위한 헬퍼와, joblib 병렬 러너(청크 단위 호출은 `predict_all.py`가 관리).

무거운 의존성(statsmodels, joblib)은 함수 내부에서 지연 import한다(`AI/CLAUDE.md`).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from app.CROWD.pipeline.lags import attach_day_lags
from app.CROWD.pipeline.lookup import TARGETS


# ── 계절 나이브(H1) ──
def attach_snaive(panel: pd.DataFrame, day_lag: int = 7) -> pd.DataFrame:
    """같은 (역, 시간대)의 `day_lag`일 전 **원본값**을 `{target}_snaive`로 붙인다.

    잔차가 아니라 원본값을 그대로 옮기는 것이 이 계열의 정의다(계획 §2) — "하루치 노이즈를
    그대로 옮긴다"는 H1을 재려면 lookup으로 걸러내지 않은 원값이어야 한다.
    """
    out = attach_day_lags(panel, TARGETS, day_lags=(day_lag,))
    return out.rename(columns={f"lag{day_lag}d_{t}": f"{t}_snaive" for t in TARGETS})


# ── OLS-AR(H3·H4 대조) ──
def fit_ols(X: np.ndarray, y: np.ndarray, min_valid_rows: int = 1) -> np.ndarray | None:
    """`y = 절편 + X·β`를 유효(모두 유한한) 행만으로 최소제곱 적합한다.

    유효 행이 `min_valid_rows` 미만이면 `None` — 값을 억지로 채우지 않고 그 시리즈를 NaN으로
    남긴다(원칙 8, `ols_series`의 유효행<30 규칙).
    """
    X = np.asarray(X, dtype="float64")
    y = np.asarray(y, dtype="float64")
    valid = np.isfinite(y) & np.isfinite(X).all(axis=1)
    n_valid = int(valid.sum())
    if n_valid < min_valid_rows:
        return None
    design = np.column_stack([np.ones(n_valid), X[valid]])
    coef, *_ = np.linalg.lstsq(design, y[valid], rcond=None)
    return coef


def predict_ols(X: np.ndarray, coef: np.ndarray | None) -> np.ndarray:
    """계수로 예측한다. 계수가 없거나(`None`) 그 행의 피처에 결측이 있으면 NaN(채우지 않는다)."""
    X = np.asarray(X, dtype="float64")
    n = len(X)
    if coef is None:
        return np.full(n, np.nan)
    finite = np.isfinite(X).all(axis=1)
    design = np.column_stack([np.ones(n), np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)])
    pred = design @ coef
    pred = np.where(finite, pred, np.nan)
    return pred


# ── SARIMAX 1단계 앞 예측(시리즈 1개) ──
def fit_predict_sarimax(
    series: pd.Series,
    order: tuple[int, int, int],
    seasonal_order: tuple[int, int, int, int],
    split_date: pd.Timestamp,
    forecast_start: pd.Timestamp,
    trend: str | None = None,
    min_train_obs: int = 30,
) -> dict:
    """시리즈 하나에 SARIMAX를 `split_date` 이전 구간으로 적합하고, refit 없이 전체 시리즈에
    적용해 `forecast_start`부터의 1단계 앞(`dynamic=False`) 예측을 낸다.

    - `series`는 **전체 달력으로 reindex된**(빠진 날 NaN) 일별 시리즈다. 칼만 필터가 NaN을 결측으로
      그대로 처리하므로 채우지 않는다(원칙 8).
    - `res.apply(series, refit=False)`로 파라미터를 고정한 채 전체 시리즈(학습+평가)에 적용한다 —
      `get_prediction(start=forecast_start).predicted_mean`은 그 시점까지의 관측만 쓴 예측이다
      (누수 없음, 테스트로 보장).
    - 학습 구간 유효 관측이 `min_train_obs` 미만이거나 적합·적용이 예외를 내면 그 시리즈는 전부
      NaN, `ok=False`로 돌아간다(개수로만 집계, 값을 지어내지 않는다).
    """
    from statsmodels.tools.sm_exceptions import ConvergenceWarning
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    import warnings

    forecast_index = series.index[series.index >= forecast_start]
    result = {
        "pred": pd.Series(np.nan, index=forecast_index, dtype="float64"),
        "ok": False,
        "n_convergence_warnings": 0,
        "error": None,
    }
    train = series[series.index < split_date]
    if int(train.notna().sum()) < min_train_obs:
        result["error"] = "insufficient_train_obs"
        return result
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = SARIMAX(
                train,
                order=order,
                seasonal_order=seasonal_order,
                trend=trend,
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            fit_res = model.fit(disp=False)
            result["n_convergence_warnings"] = sum(
                1 for w in caught if issubclass(w.category, ConvergenceWarning)
            )
        applied = fit_res.apply(series, refit=False)
        pred = applied.get_prediction(start=forecast_start, dynamic=False).predicted_mean
        result["pred"] = pred.reindex(forecast_index)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001 — 시리즈별 실패는 개수로만 남긴다(계획 §2)
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


# ── 병렬 러너 ──
def build_wide_series(
    frame: pd.DataFrame,
    value_cols: Sequence[str],
    full_dates: pd.DatetimeIndex,
    keys: tuple[str, str] = ("station_no", "time_slot"),
    date_col: str = "date",
) -> pd.DataFrame:
    """(date × 역 × 시간대) 긴 프레임을 열 `MultiIndex(value, station_no, time_slot)`인 넓은 표로 바꾼다.

    시리즈 10,920개를 하나씩 날짜 조인하는 대신 pivot 한 번으로 잘라 쓰기 위한 준비 단계다.
    `full_dates`로 전체 달력에 reindex한다 — 원래 없던 날은 NaN(원칙 8).
    """
    wide = frame.pivot_table(
        index=date_col, columns=list(keys), values=list(value_cols), aggfunc="first"
    )
    return wide.reindex(full_dates)


def run_sarima_batch(
    wide: pd.DataFrame,
    keys: Sequence[tuple],
    order: tuple[int, int, int],
    seasonal_order: tuple[int, int, int, int],
    split_date: pd.Timestamp,
    forecast_start: pd.Timestamp,
    trend: str | None = None,
    n_jobs: int = -1,
) -> pd.DataFrame:
    """`keys`(넓은 표의 열 = (value, station_no, time_slot))로 지정한 시리즈들을 병렬로 적합·예측한다.

    이 함수는 **한 번의 호출 단위(청크)** 만 처리한다 — 전체 10,920시리즈를 몇 개로 나눠 청크마다
    parquet에 저장하고 중단 시 재개하는 것은 호출자(`predict_all.py`)의 책임이다(`AI/CLAUDE.md`
    "실험 실행 효율" — 긴 실행은 백그라운드 + 청크 저장).

    반환: `target, station_no, time_slot, date, pred, ok, error, n_convergence_warnings` 롱 프레임.
    """
    from joblib import Parallel, delayed

    def _one(key: tuple) -> pd.DataFrame:
        value_col, station_no, time_slot = key
        series = wide[key]
        res = fit_predict_sarimax(series, order, seasonal_order, split_date, forecast_start, trend)
        n = len(res["pred"])
        if n == 0:
            return pd.DataFrame(
                columns=[
                    "target",
                    "station_no",
                    "time_slot",
                    "date",
                    "pred",
                    "ok",
                    "error",
                    "n_convergence_warnings",
                ]
            )
        return pd.DataFrame(
            {
                "target": value_col,
                "station_no": station_no,
                "time_slot": time_slot,
                "date": res["pred"].index,
                "pred": res["pred"].to_numpy(dtype="float64"),
                "ok": res["ok"],
                "error": res["error"],
                "n_convergence_warnings": res["n_convergence_warnings"],
            }
        )

    parts = Parallel(n_jobs=n_jobs)(delayed(_one)(k) for k in keys)
    if not parts:
        return pd.DataFrame(
            columns=[
                "target",
                "station_no",
                "time_slot",
                "date",
                "pred",
                "ok",
                "error",
                "n_convergence_warnings",
            ]
        )
    return pd.concat(parts, ignore_index=True)
