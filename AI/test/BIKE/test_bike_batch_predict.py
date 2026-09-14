"""BIKE 배치 예측 산출물 저장 계약."""

from __future__ import annotations

import json

import pandas as pd

from app.BIKE.pipeline import batch_predict


class FakePredictor:
    kind = "avg"
    version = "avg:test"

    def predict_all(self) -> pd.DataFrame:
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

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["source"] == "avg"
    assert meta["artifact"] == artifact_dir.name
    assert meta["rows"] == 1
    assert meta["stations"] == 1
