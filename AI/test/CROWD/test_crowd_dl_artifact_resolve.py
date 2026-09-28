"""197 B-3 — `resolve_predictor`의 `dl` kind는 이름 정렬(`latest_artifact`)이 아니라
`settings.crowd_dl_artifact`로 고정된 폴더명을 쓴다. torch가 없어도 도는 부분만 검증한다
(`DLPredictor` 생성 자체는 torch가 필요해 `test_crowd_dl_predictor.py`가 따로 다룬다).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.CROWD.pipeline.batch_predict import resolve_predictor


def _settings(models_dir, dl_artifact: str) -> SimpleNamespace:
    return SimpleNamespace(crowd_models_dir=models_dir, crowd_dl_artifact=dl_artifact)


def test_resolve_dl_raises_file_not_found_when_configured_artifact_missing(tmp_path):
    settings = _settings(tmp_path, "dl_gru_s14_noev_s42_20260914-1358")
    with pytest.raises(FileNotFoundError, match="crowd_dl_artifact"):
        resolve_predictor("dl", panel_train=None, settings=settings)


def test_resolve_dl_raises_value_error_when_configured_folder_is_not_dl_kind(tmp_path):
    art = tmp_path / "festival_selflag_d1sd_d7_resid_20260913-0340"
    art.mkdir()
    (art / "meta.json").write_text(json.dumps({"feature_set": "x"}), encoding="utf-8")
    settings = _settings(tmp_path, art.name)
    with pytest.raises(ValueError, match="model_kind"):
        resolve_predictor("dl", panel_train=None, settings=settings)
