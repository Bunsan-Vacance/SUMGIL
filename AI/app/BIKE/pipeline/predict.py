"""아티팩트 로딩 → 예측 재구성.

`train.py`가 저장한 디렉터리 하나를 읽어 `Predictor`를 만든다. 지금은 `avg` 소스만
지원한다(`predictor.py`의 `LightGBMPredictor`는 미구현 — B4 model 소스 보류).

배치 잡(`batch_predict.py`, B6에서 작성 예정)이 이 함수로 예측기를 만들고, 서빙
디렉터리(`data/BIKE/serving/`)에 최종 `bike_stock_pred_*.parquet`을 쓴다. 여기서는
아티팩트 → Predictor 재구성과 표 생성까지만 다룬다.

실행:
    cd AI
    python -m app.BIKE.pipeline.predict --artifact models/BIKE/<dir> --out /tmp/preview.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.BIKE.pipeline.predictor import AvgPredictor, Predictor


def load_predictor(artifact_dir: Path, kind: str = "avg") -> Predictor:
    artifact_dir = Path(artifact_dir)
    if kind == "avg":
        return AvgPredictor.load(artifact_dir / "stock_profile_avg.parquet")
    raise ValueError(
        f"kind={kind!r}는 아직 지원 안 함 — avg만 가능(predictor.py의 LightGBMPredictor 참고)"
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--artifact", required=True, help="models/BIKE/<dir>")
    ap.add_argument("--kind", default="avg", choices=["avg"])
    ap.add_argument("--out", default=None, help="저장할 parquet 경로(생략 시 표준 출력에 요약)")
    args = ap.parse_args(argv)

    predictor = load_predictor(Path(args.artifact), args.kind)
    table = predictor.predict_all()
    if args.out:
        table.to_parquet(args.out, index=False)
        print(f"[예측] 저장: {args.out} ({len(table):,}행, predictor={predictor.version})")
    else:
        print(table.head(20).to_string(index=False))
        print(
            f"\n총 {len(table):,}행, station {table['rental_id'].nunique()}개, predictor={predictor.version}"
        )


if __name__ == "__main__":
    main(sys.argv[1:])
