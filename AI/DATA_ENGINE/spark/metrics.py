"""pandas vs Spark 결과 대조 지표 (274) — 165·273과 같은 원칙(정확성을 속도보다 먼저 본다).

새 Spark 잡을 만들 때마다 대조 코드를 새로 짜지 않도록 공통화한다. torch·PySpark 규약과
달리 이 모듈은 pandas·numpy만 쓴다 — Spark 결과를 이미 `toPandas()`로 받은 뒤에 비교하는
용도라 pyspark를 직접 import하지 않는다(가볍게 유지, 테스트에 importorskip 불필요).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compare_frames(
    pandas_df: pd.DataFrame,
    spark_df: pd.DataFrame,
    key_cols: list[str],
    value_cols: list[str],
) -> dict:
    """두 결과를 `key_cols` 기준으로 정렬·대조한다.

    행수가 다르면 `rows_match=False`로 표시하고, 공통 키에 대해서만 `value_cols`의 최대
    절대오차를 잰다. 273에서 실제로 이 함수 형태의 대조가 두 번(entity_id 검증 누락,
    타임존 이중 변환) 정확도 실패를 잡아냈다 — 값이 일치할 때까지는 처리 시간 비교를
    믿지 않는다.
    """
    left = pandas_df.set_index(key_cols).sort_index()
    right = spark_df.set_index(key_cols).sort_index()
    common_idx = left.index.intersection(right.index)
    rows_match = len(left) == len(right) == len(common_idx)

    max_abs_err = 0.0
    for col in value_cols:
        if col not in left.columns or col not in right.columns:
            continue
        a = left.loc[common_idx, col].to_numpy(dtype=float)
        b = right.loc[common_idx, col].to_numpy(dtype=float)
        if len(a):
            max_abs_err = max(max_abs_err, float(np.nanmax(np.abs(a - b))))

    return {
        "rows_pandas": len(left),
        "rows_spark": len(right),
        "rows_match": rows_match,
        "max_abs_err": max_abs_err,
    }
