"""예측 판 아카이브 — serving 폴더의 예측 parquet과 meta를 `dt=D/gen=<generated_at>/`로 복사한다.

서빙 폴더의 `predictions_<D>.parquet`은 배치가 다시 돌면 덮어써진다. 채점은 D일 실측이 들어온 뒤
이뤄지므로, 누수 가드를 통과하는 판(D 종료 전에 만든 판)을 잃지 않도록 판마다 복사해 둔다.

- 대상 날짜 D는 파일명 `predictions_<D>.parquet`에서 읽는다(`score.find_prediction_candidates`와 같다).
- `gen=`은 meta의 `generated_at`을 KST `YYYYMMDDTHHMMSS`로 바꾼 값이다.
- 같은 `dt/gen` 폴더가 이미 있으면 건너뛴다(멱등). meta가 없거나 읽을 수 없는 판은 건너뛴다.
- 임시 폴더에 쓴 뒤 rename해서 반쯤 복사된 폴더가 채점에 보이지 않게 한다.
- 보존(삭제) 정책은 두지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from app.CROWD.pipeline.retrain.common import (
    PRED_ARCHIVE_DIR,
    SERVING_DIR,
    parse_generated_at,
    read_json,
)
from app.CROWD.pipeline.retrain.score import _meta_path

_NAME_RE = re.compile(r"^predictions_(\d{4}-\d{2}-\d{2})\.parquet$")


def archive_predictions(serving_dir: Path, archive_dir: Path) -> dict:
    """serving의 예측 판을 아카이브로 복사한다. `archived`·`skipped_existing`·`skipped_no_meta`."""
    serving_dir, archive_dir = Path(serving_dir), Path(archive_dir)
    result: dict = {"archived": [], "skipped_existing": [], "skipped_no_meta": []}
    for path in sorted(serving_dir.glob("predictions_*.parquet")):
        match = _NAME_RE.match(path.name)
        if match is None:
            continue
        meta_src = _meta_path(path)
        meta = read_json(meta_src)
        generated = meta.get("generated_at") if meta else None
        if not generated:
            result["skipped_no_meta"].append(path.name)
            continue
        gen = f"{parse_generated_at(str(generated)):%Y%m%dT%H%M%S}"
        label = f"dt={match.group(1)}/gen={gen}"
        dest = archive_dir / label
        if dest.exists():
            result["skipped_existing"].append(label)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.parent / f".tmp-gen={gen}"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            tmp.mkdir()
            shutil.copy2(path, tmp / path.name)
            shutil.copy2(meta_src, tmp / meta_src.name)
            tmp.rename(dest)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        result["archived"].append(label)
    return result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="예측 판 아카이브(serving → pred_archive)")
    ap.add_argument("--serving-dir", default=str(SERVING_DIR))
    ap.add_argument("--archive-dir", default=str(PRED_ARCHIVE_DIR))
    args = ap.parse_args(argv)
    result = archive_predictions(Path(args.serving_dir), Path(args.archive_dir))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
