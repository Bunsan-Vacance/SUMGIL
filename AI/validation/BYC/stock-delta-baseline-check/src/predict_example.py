from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one prediction with the saved best model.")
    default_output_dir = Path(__file__).resolve().parents[1] / "outputs"
    parser.add_argument("--model-path", default=str(default_output_dir / "best_model.pkl"))
    parser.add_argument("--schema-path", default=str(default_output_dir / "feature_schema.json"))
    return parser.parse_args()


def station_code(station_id: str, station_categories: list[str]) -> int:
    try:
        return station_categories.index(str(station_id))
    except ValueError:
        return -1


def main() -> None:
    args = parse_args()
    model_bundle = joblib.load(args.model_path)
    schema = json.loads(Path(args.schema_path).read_text(encoding="utf-8"))

    sample = {
        "station_id": "ST-102",
        "horizon_min": 10,
        "current_stock": 3,
        "capacity_proxy": 20,
        "stock_ratio_proxy": 0.15,
        "rent_count_5m": 1,
        "return_count_5m": 0,
        "net_delta_5m": -1,
        "rent_recent_15m": 4,
        "return_recent_15m": 1,
        "net_recent_15m": -3,
        "net_recent_30m": -5,
        "net_recent_60m": -7,
        "stock_delta_prev_5m": -1,
        "stock_delta_prev_15m": -3,
        "stock_delta_prev_60m": -7,
        "hour": 18,
        "minute": 30,
        "day_of_week": 1,
        "is_weekend": 0,
    }

    sample["station_code"] = station_code(sample["station_id"], schema["station_categories"])
    frame = pd.DataFrame([sample])

    model = model_bundle["model"]
    model_name = model_bundle["model_name"]
    if model_name == "Naive_15m_trend":
        predicted_delta = (frame["net_recent_15m"] / 15 * frame["horizon_min"]).iloc[0]
    elif model_name == "Naive_60m_trend":
        predicted_delta = (frame["net_recent_60m"] / 60 * frame["horizon_min"]).iloc[0]
    else:
        x = frame[schema["model_feature_cols"]].fillna(0)
        predicted_delta = float(model.predict(x)[0])

    predicted_stock = float(sample["current_stock"] + predicted_delta)
    shortage_risk = predicted_stock <= schema["shortage_threshold"]

    print(
        json.dumps(
            {
                "model": model_name,
                "predicted_delta": predicted_delta,
                "predicted_stock": predicted_stock,
                "shortage_risk": shortage_risk,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
