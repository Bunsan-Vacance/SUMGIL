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
- `source_signature` / `chunk_signature` / `chunk_cache_valid` — 청크 캐시가 **어떤 입력으로 만든
  예측인지**를 남기고 대조하는 순수 함수. 패널이 바뀌었는데 옛 청크를 그대로 재사용하면 낡은
  예측으로 표가 나온다(맥 실행에서 실제로 겪은 함정) — `dataset._cache_meta`와 같은 방식이다.
- `missing_feature_columns` — 평가 프레임에 배포 세트 피처가 다 있는지 보는 가드.
- `divergence_bounds` / `apply_bounds` — SARIMA가 드물게 내는 발산 예측의 처리. 상한은 **학습 구간
  실측 최댓값**에서만 정하고(평가 구간을 보지 않는다), 주 표는 자른 값으로 **채점에 포함**한다.
  결측으로 되돌려 빼면 그 모형의 최악 오차가 평가에서 사라져 그 모형에 유리해진다.

무거운 의존성(statsmodels, joblib)은 함수 내부에서 지연 import한다(`AI/CLAUDE.md`).
"""

from __future__ import annotations

import json
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
    enforce_stationarity: bool = False,
    enforce_invertibility: bool = False,
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
    - `enforce_stationarity`/`enforce_invertibility`는 기본 False다(근단위근 계열의 수렴 실패를
      줄이려던 선택). 대신 결측 구간에서 개루프 전파로 발산하는 예측이 드물게 나오므로, True
      변형을 따로 돌려 시간·실패율·발산을 비교한다(`predict_all.py --enforce-stationarity`).
    """
    import warnings

    from statsmodels.tools.sm_exceptions import ConvergenceWarning
    from statsmodels.tsa.statespace.sarimax import SARIMAX

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
                enforce_stationarity=enforce_stationarity,
                enforce_invertibility=enforce_invertibility,
            )
            fit_res = model.fit(disp=False)
            result["n_convergence_warnings"] = sum(
                1 for w in caught if issubclass(w.category, ConvergenceWarning)
            )
        applied = fit_res.apply(series, refit=False)
        pred = applied.get_prediction(start=forecast_start, dynamic=False).predicted_mean
        result["pred"] = pred.reindex(forecast_index)
        result["ok"] = True
    except Exception as exc:
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
    enforce_stationarity: bool = False,
    enforce_invertibility: bool = False,
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
        res = fit_predict_sarimax(
            series,
            order,
            seasonal_order,
            split_date,
            forecast_start,
            trend,
            enforce_stationarity=enforce_stationarity,
            enforce_invertibility=enforce_invertibility,
        )
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


# ── 피처 누락 가드 ──
def missing_feature_columns(columns: Sequence[str], feature_cols: Sequence[str]) -> list[str]:
    """`feature_cols` 중 프레임에 **없는** 컬럼. 비어 있어야 정상이다.

    `features.build_matrix`는 없는 컬럼을 NaN으로 채운다(서빙에서 실시간 열이 아직 없을 때를 위한
    설계다). 평가 스크립트가 파생 캐시에서 열을 덜 읽으면 그 피처가 통째로 결측인 채 예측이 나가
    **비교 대상만 조용히 약해진다** — 실제로 이벤트 5열이 빠져 LightGBM RMSE 개선율이 23.38 →
    21.80으로 낮게 나왔다. 그래서 예측 직전에 이 함수로 막는다.
    """
    have = set(map(str, columns))
    return [c for c in feature_cols if c not in have]


# ── 청크 캐시 지문(입력 조건 메타) ──
def source_signature(
    frame: pd.DataFrame,
    value_cols: Sequence[str],
    date_col: str = "date",
    extra: dict | None = None,
) -> dict:
    """청크 예측이 **어떤 입력으로 만들어졌는지**를 나타내는 지문.

    행 수·날짜 범위만으로는 88번 요일유형 수정처럼 "행 수는 같고 값이 바뀐" 판을 구분하지 못한다.
    유효값 개수와 합(`checksum`)까지 넣어 값이 바뀌면 달라지게 한다. `extra`로 패널 파일 mtime 같은
    바깥 정보를 얹는다(`dataset._cache_meta`와 같은 방식).
    """
    values = frame[list(value_cols)].to_numpy(dtype="float64")
    finite = np.isfinite(values)
    sig = {
        "rows": len(frame),
        "value_cols": [str(c) for c in value_cols],
        "date_min": str(pd.Timestamp(frame[date_col].min()).date()),
        "date_max": str(pd.Timestamp(frame[date_col].max()).date()),
        "n_finite": int(finite.sum()),
        "checksum": round(float(values[finite].sum()), 3),
    }
    if extra:
        sig.update(extra)
    return sig


def chunk_signature(
    source_sig: dict,
    spec: dict,
    split_date: pd.Timestamp,
    forecast_start: pd.Timestamp,
    stations: Sequence[int],
) -> dict:
    """청크 하나의 재사용 조건 — 입력 지문 + 모형 사양 + 구간 + 그 청크가 맡은 역 목록."""
    return {
        "source": source_sig,
        "order": list(spec["order"]),
        "seasonal_order": list(spec["seasonal_order"]),
        "trend": spec.get("trend"),
        "enforce_stationarity": bool(spec.get("enforce_stationarity", False)),
        "enforce_invertibility": bool(spec.get("enforce_invertibility", False)),
        "split_date": str(pd.Timestamp(split_date).date()),
        "forecast_start": str(pd.Timestamp(forecast_start).date()),
        "stations": [int(s) for s in stations],
    }


def chunk_cache_valid(have: dict | None, want: dict) -> bool:
    """저장된 meta가 지금 만들려는 청크와 같은 조건인지. 다르면 그 청크는 다시 계산한다.

    JSON 왕복을 거치면 튜플이 리스트가 되므로 양쪽 다 정규화해 비교한다.
    """
    if not isinstance(have, dict):
        return False
    return json.loads(json.dumps(have, sort_keys=True)) == json.loads(
        json.dumps(want, sort_keys=True)
    )


# ── 발산 예측 처리 ──
def divergence_bounds(
    train: pd.DataFrame, targets: Sequence[str], low: float = 0.0
) -> dict[str, tuple[float, float]]:
    """타깃별 `[하한, 상한]`. **상한은 학습 구간 실측 최댓값**이다 — 평가 구간 값을 보지 않는다.

    하한 0은 "인원은 음수가 될 수 없다"는 물리 제약이고, 서빙 변환 층도 같은 자리에서 자른다
    (`dl-resid-check/evaluate_dl.grade_agreement`의 `np.clip(pred, 0, None)`).
    """
    out: dict[str, tuple[float, float]] = {}
    for t in targets:
        values = train[t].to_numpy(dtype="float64")
        out[t] = (float(low), float(np.nanmax(values)))
    return out


def apply_bounds(
    values: np.ndarray, low: float, high: float, mode: str = "clip"
) -> tuple[np.ndarray, dict[str, int]]:
    """예측을 `[low, high]` 기준으로 처리하고 걸린 개수를 함께 돌려준다.

    - `clip`(주 표): 양끝을 자른다 — 발산 행이 **상한으로 채점에 포함**된다. 결측으로 빼면 그
      모형의 최악 오차가 평가에서 사라져 그 모형에 유리해진다.
    - `drop`(민감도): 하한은 자르고 **상한 초과만 NaN**으로 되돌린다(맥 실행의 옛 방식). `clip`과의
      차이가 발산 처리 자체의 효과다.
    - `raw`: 아무것도 하지 않는다(레지스트리 수치와 맞춰 볼 때).
    """
    if mode not in {"clip", "drop", "raw"}:
        raise ValueError(f"알 수 없는 발산 처리 모드: {mode}")
    out = np.asarray(values, dtype="float64").copy()
    finite = np.isfinite(out)
    n_low = int((finite & (out < low)).sum())
    n_high = int((finite & (out > high)).sum())
    if mode == "raw":
        return out, {"n_low": n_low, "n_high": n_high}
    out = np.where(finite & (out < low), low, out)
    if mode == "clip":
        out = np.where(np.isfinite(out) & (out > high), high, out)
    else:
        out = np.where(np.isfinite(out) & (out > high), np.nan, out)
    return out, {"n_low": n_low, "n_high": n_high}
