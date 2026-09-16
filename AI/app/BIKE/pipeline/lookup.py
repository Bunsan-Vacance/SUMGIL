"""avg baseline — station × dow_type × time_slot 재고·확률 평균 조회.

CROWD의 `lookup.py`(요일유형×역×시간대 승하차 평균)와 같은 위상이다 — 모델 없이 실측값을
직접 평균 내는 "정직한 기준선"이고, `source=avg`로 그대로 서빙에 들어간다.
`validation/BYC/full-coverage-check/src/stock_probability.py`에서 검증된 계산을 승격했다.

    exp_bikes  = 그 그룹의 stock_anchor_hour 평균
    p_empty    = 그 그룹에서 재고==0(is_empty_anchor)인 비율
    p_full     = 그 그룹에서 재고>=rack_count(is_full_anchor)인 비율

**조회 실패 처리**: 표본이 없는 (station, dow_type, time_slot) 조합은 행을 만들지 않는다
(전체 평균으로 채우면 실제보다 좋아 보이고, 서빙에서는 "데이터 없음"으로 봐야 한다 —
데이터 검증 리포트 원칙 8).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.BIKE.pipeline.calendar import attach_dow_type, load_holidays, slot_5m_to_time_slot

STOCK_KEYS = ["od_station_id", "dow_type", "time_slot"]
STOCK_NEEDED_COLS = [
    "od_station_id",
    "date",
    "slot_5m",
    "stock_anchor_hour",
    "is_empty_anchor",
    "is_full_anchor",
    "rack_count",
]


class StockProfileBaseline:
    """station × dow_type × time_slot 재고 평균·empty/full 빈도. train 기간으로만 fit한다."""

    def __init__(self) -> None:
        self.table_: pd.DataFrame | None = None

    def fit_streaming(
        self, paths: list[Path], holidays: pd.DataFrame | None = None
    ) -> StockProfileBaseline:
        """여러 parquet을 순회하며 그룹별 부분합(sum·count)을 누적한다.

        전체를 한 번에 메모리에 안 올린다 — sum/count를 파일 단위로 합산하면 전체를
        한 번에 읽은 것과 수학적으로 동일한 평균이 나온다(MapReduce의 mean과 같은 원리).
        """
        if holidays is None:
            holidays = load_holidays()
        total = None
        for p in paths:
            df = pd.read_parquet(p, columns=[*STOCK_NEEDED_COLS, "horizon_min"])
            df = df[df["horizon_min"] == 5]  # base_time당 1행만(horizon 4종 중복 제거)
            df = df.dropna(subset=["stock_anchor_hour"])
            df = attach_dow_type(df, holidays)
            df["time_slot"] = slot_5m_to_time_slot(df["slot_5m"])

            g = df.groupby(STOCK_KEYS).agg(
                exp_bikes_sum=("stock_anchor_hour", "sum"),
                n=("stock_anchor_hour", "count"),
                empty_sum=("is_empty_anchor", "sum"),
                full_sum=("is_full_anchor", "sum"),
            )
            total = g if total is None else total.add(g, fill_value=0)
            del df

        total["exp_bikes"] = total["exp_bikes_sum"] / total["n"]
        total["p_empty"] = total["empty_sum"] / total["n"]
        total["p_full"] = total["full_sum"] / total["n"]
        self.table_ = total.reset_index()[[*STOCK_KEYS, "exp_bikes", "p_empty", "p_full"]]
        return self

    def predict(self) -> pd.DataFrame:
        """전체 (station, dow_type, time_slot) 조합의 표를 그대로 돌려준다(표본 있는 것만)."""
        if self.table_ is None:
            raise RuntimeError("fit_streaming()을 먼저 호출해야 한다.")
        return self.table_.rename(columns={"od_station_id": "rental_id"}).copy()

    # ── 아티팩트 ──
    def save(self, path: Path) -> Path:
        if self.table_ is None:
            raise RuntimeError("fit_streaming()을 먼저 호출해야 한다.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.table_.to_parquet(path, index=False)
        return path

    @classmethod
    def load(cls, path: Path) -> StockProfileBaseline:
        model = cls()
        model.table_ = pd.read_parquet(path)
        return model
