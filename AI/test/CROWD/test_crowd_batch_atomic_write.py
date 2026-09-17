"""197 C부 — 배치 산출물 쓰기가 원자적인지 검증한다.

FastAPI가 서빙 디렉터리를 상시로 읽으므로(`.claude/handoff/TO_BE-infra-serving.md`), 배치가
그 경로를 직접 덮어쓰면 쓰는 도중의 반쯤 쓰인 파일을 볼 수 있다. `_atomic_write`는 임시 파일에
쓰고 `rename`으로 교체해 이 창을 없앤다 — 여기서는 실제 배치 데이터 없이 그 계약(성공 시 교체·
실패 시 원본 보존·임시 파일 미잔존)만 확인한다.
"""

from __future__ import annotations

import pytest

from app.CROWD.pipeline.batch_predict import _atomic_write


def test_atomic_write_replaces_target_and_leaves_no_tmp_file(tmp_path):
    path = tmp_path / "predictions_2025-10-03.parquet"
    path.write_text("이전 산출물", encoding="utf-8")

    _atomic_write(lambda p: p.write_text("새 산출물", encoding="utf-8"), path)

    assert path.read_text(encoding="utf-8") == "새 산출물"
    assert not path.with_name(f"{path.name}.tmp").exists()


def test_atomic_write_creates_new_file_when_none_existed(tmp_path):
    path = tmp_path / "predictions_2025-10-03.meta.json"

    _atomic_write(lambda p: p.write_text("{}", encoding="utf-8"), path)

    assert path.read_text(encoding="utf-8") == "{}"
    assert not path.with_name(f"{path.name}.tmp").exists()


def test_atomic_write_keeps_existing_file_and_drops_tmp_on_failure(tmp_path):
    path = tmp_path / "predictions_2025-10-03.parquet"
    path.write_text("기존 산출물", encoding="utf-8")

    def _write_then_fail(p):
        p.write_text("반쯤 쓰다 실패", encoding="utf-8")
        raise RuntimeError("쓰기 실패(가정)")

    with pytest.raises(RuntimeError, match="쓰기 실패"):
        _atomic_write(_write_then_fail, path)

    assert path.read_text(encoding="utf-8") == "기존 산출물"
    assert not path.with_name(f"{path.name}.tmp").exists()
