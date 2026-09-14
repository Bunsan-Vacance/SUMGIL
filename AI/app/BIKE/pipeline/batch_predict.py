"""배치 예측 잡 — 최신 아티팩트에서 표를 만들어 서빙 디렉터리에 저장한다.

    models/BIKE/<tag>_<시각>/  (train.py 아티팩트, 지정 없으면 가장 최근 것)
      → Predictor.predict_all()                                     avg 소스(기본값)
      → data/BIKE/serving/bike_stock_pred_<생성시각>.parquet + .csv + .meta.json

API(`app/BIKE/service.py`)는 이 디렉터리에서 가장 최신 파일 하나만 읽는다(`AI/CLAUDE.md`:
서빙 경로는 가벼운 의존성만 — lightgbm은 여기서도 predictor.py를 통해서만 지연 import된다).

CROWD의 `batch_predict.py`와 같은 위상이지만 BIKE는 날짜 축이 없는 정적 표
(`bike_stock_pred`의 기본키가 rental_id·dow_type·time_slot)라 훨씬 단순하다 — 대상 날짜별
패널 조립·재귀식·보정 없이, 아티팩트의 표를 그대로 서빙 파일명 규칙에 맞춰 저장하는 게 전부다.
`--predictor lightgbm`은 아직 `predictor.py`의 `LightGBMPredictor.predict_all()`이
`NotImplementedError`라 지금은 쓸 수 없다(B4 model 소스, 2026-09-14 보류) — 기본값은 avg다.

실행:
    cd AI
    python -m app.BIKE.pipeline.batch_predict                          # 최신 아티팩트, 기본 predictor(avg)
    python -m app.BIKE.pipeline.batch_predict --artifact models/BIKE/smoke-promoted_20260914-0204
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.BIKE.pipeline.predictor import Predictor, build_predictor, latest_artifact
from app.core.config import get_settings


def resolve_predictor(kind: str, artifact_dir: Path) -> Predictor:
    """설정값·아티팩트 → 예측기."""
    if kind == "avg":
        return build_predictor("avg", baseline_path=artifact_dir / "stock_profile_avg.parquet")
    if kind == "lightgbm":
        return build_predictor("lightgbm", model_dir=artifact_dir)
    raise ValueError(f"알 수 없는 예측기: {kind} (가능: avg, lightgbm)")


def run(
    artifact_dir: Path | None = None,
    predictor_kind: str | None = None,
    out_dir: Path | None = None,
) -> Path:
    settings = get_settings()
    out_dir = Path(out_dir or settings.bike_serving_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    artifact_dir = Path(artifact_dir) if artifact_dir else latest_artifact(settings.bike_models_dir)
    if artifact_dir is None:
        raise FileNotFoundError(
            f"아티팩트가 없다: {settings.bike_models_dir} — train.py를 먼저 돌린다"
        )

    predictor = resolve_predictor(predictor_kind or settings.bike_predictor, artifact_dir)
    table = predictor.predict_all()

    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"bike_stock_pred_{stamp}.parquet"
    table.to_parquet(path, index=False)
    table.to_csv(path.with_suffix(".csv"), index=False)

    meta = {
        # source: service.py의 BikeMetaResponse.source(avg|model) 계약과 이름을 맞춘다.
        "source": predictor.kind,
        "artifact": artifact_dir.name,
        "predictor_version": predictor.version,
        "rows": len(table),
        "stations": int(table["rental_id"].nunique()),
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
    }
    path.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(f"[배치] {path.name} ({len(table):,}행, {predictor.version})", flush=True)
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--artifact", default=None, help="models/BIKE/<dir> (생략 시 가장 최근 것)")
    ap.add_argument("--predictor", default=None, help="avg|lightgbm (기본: 설정값 avg)")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)
    run(
        Path(args.artifact) if args.artifact else None,
        args.predictor,
        Path(args.out_dir) if args.out_dir else None,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
