"""예측 판 아카이브(`app/CROWD/pipeline/retrain/archive.py`) — 합성 파일로 복사·멱등성 검사."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.CROWD.pipeline.retrain import archive as ar

DAY = "2026-09-10"


def write_pred(serving: Path, day: str, generated_at: str | None) -> Path:
    path = serving / f"predictions_{day}.parquet"
    pd.DataFrame({"date": [day], "station_no": [101]}).to_parquet(path, index=False)
    if generated_at is not None:
        meta = {"generated_at": generated_at, "in_panel": False}
        path.with_suffix(".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return path


def snapshot(serving: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(serving.iterdir())}


def test_archive_copies_and_is_idempotent(tmp_path):
    serving, archive = tmp_path / "serving", tmp_path / "pred_archive"
    serving.mkdir()
    write_pred(serving, DAY, "2026-09-10T06:00:00+09:00")
    write_pred(serving, "2026-09-11", "2026-09-11T06:30:15+09:00")
    write_pred(serving, "2026-09-12", None)
    before = snapshot(serving)

    first = ar.archive_predictions(serving, archive)

    assert sorted(first["archived"]) == [
        "dt=2026-09-10/gen=20260910T060000",
        "dt=2026-09-11/gen=20260911T063015",
    ]
    assert first["skipped_existing"] == []
    assert first["skipped_no_meta"] == ["predictions_2026-09-12.parquet"]
    gen_dir = archive / "dt=2026-09-10" / "gen=20260910T060000"
    assert sorted(p.name for p in gen_dir.iterdir()) == [
        "predictions_2026-09-10.meta.json",
        "predictions_2026-09-10.parquet",
    ]
    assert not (archive / "dt=2026-09-12").exists()
    assert not list(archive.rglob(".tmp-*"))
    assert snapshot(serving) == before

    second = ar.archive_predictions(serving, archive)

    assert second["archived"] == []
    assert len(second["skipped_existing"]) == 2
    assert second["skipped_no_meta"] == ["predictions_2026-09-12.parquet"]
    assert snapshot(serving) == before
