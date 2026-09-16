"""BIKE 배치 예측 산출물 저장 계약."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from app.BIKE.pipeline import batch_predict
from app.BIKE.pipeline.lookup import StockProfileBaseline
from app.BIKE.pipeline.predictor import AvgPredictor


class FakePredictor:
    kind = "avg"
    version = "avg:test"

    def predict_all(self, target_date: date | None = None) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "rental_id": "ST-1",
                    "dow_type": 0,
                    "time_slot": 16,
                    "exp_bikes": 12.5,
                    "p_empty": 0.05,
                    "p_full": 0.1,
                    "source": "avg",
                    "prediction_source": "observed_avg",
                }
            ]
        )


def test_batch_predict_writes_parquet_csv_and_meta(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "models" / "BIKE" / "avg-test_20260914-0000"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "meta.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(batch_predict, "resolve_predictor", lambda *_args: FakePredictor())

    path = batch_predict.run(artifact_dir=artifact_dir, predictor_kind="avg", out_dir=tmp_path)

    csv_path = path.with_suffix(".csv")
    meta_path = path.with_suffix(".meta.json")

    assert path.exists()
    assert csv_path.exists()
    assert meta_path.exists()

    parquet = pd.read_parquet(path)
    csv = pd.read_csv(csv_path)
    assert parquet.to_dict("records") == csv.to_dict("records")
    assert csv.loc[0, "rental_id"] == "ST-1"
    assert csv.loc[0, "prediction_source"] == "observed_avg"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["source"] == "avg"
    assert meta["artifact"] == artifact_dir.name
    assert meta["rows"] == 1
    assert meta["stations"] == 1


def test_avg_predictor_expands_observed_stations_with_station_only_fallback():
    baseline = StockProfileBaseline()
    baseline.table_ = pd.DataFrame(
        [
            {
                "od_station_id": "ST-1",
                "dow_type": 0,
                "time_slot": 5,
                "exp_bikes": 10.0,
                "p_empty": 0.1,
                "p_full": 0.2,
            },
            {
                "od_station_id": "ST-1",
                "dow_type": 1,
                "time_slot": 5,
                "exp_bikes": 20.0,
                "p_empty": 0.3,
                "p_full": 0.4,
            },
            {
                "od_station_id": "ST-2",
                "dow_type": 0,
                "time_slot": 5,
                "exp_bikes": 100.0,
                "p_empty": 0.8,
                "p_full": 0.9,
            },
        ]
    )

    out = AvgPredictor(baseline).predict_all()

    assert len(out) == 2 * 3 * 48
    assert set(out["rental_id"]) == {"ST-1", "ST-2"}
    assert out[["rental_id", "dow_type", "time_slot"]].duplicated().sum() == 0
    assert set(out["source"]) == {"avg"}

    observed = out[
        (out["rental_id"] == "ST-1") & (out["dow_type"] == 0) & (out["time_slot"] == 5)
    ].iloc[0]
    assert observed["exp_bikes"] == 10.0
    assert observed["prediction_source"] == "observed_avg"

    station_time = out[
        (out["rental_id"] == "ST-1") & (out["dow_type"] == 2) & (out["time_slot"] == 5)
    ].iloc[0]
    assert station_time["exp_bikes"] == 15.0
    assert station_time["p_empty"] == pytest.approx(0.2)
    assert station_time["p_full"] == pytest.approx(0.3)
    assert station_time["prediction_source"] == "station_time_fallback"

    station_global = out[
        (out["rental_id"] == "ST-1") & (out["dow_type"] == 2) & (out["time_slot"] == 6)
    ].iloc[0]
    assert station_global["exp_bikes"] == 15.0
    assert station_global["prediction_source"] == "station_global_fallback"
