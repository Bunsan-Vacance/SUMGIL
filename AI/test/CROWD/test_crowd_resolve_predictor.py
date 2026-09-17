"""145 후속 — `resolve_predictor`의 LightGBM 아티팩트 고정(`crowd_lgbm_artifact`) 테스트.

DL(197 B-3, `test_crowd_dl_artifact_resolve.py`)과 같은 방식으로 LightGBM도
`settings.crowd_lgbm_artifact`로 폴더명을 고정한다(`_lightgbm_artifact`). `lightgbm`·torch가
없어도 도는 부분만 검증한다 — `build_predictor`를 스텁으로 바꿔치기해 실제 모델을 만들지 않고
`auto`/`lightgbm` 분기가 어떤 아티팩트를 골랐는지(`kind`, `cfg`)만 본다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.CROWD.pipeline import batch_predict
from app.CROWD.pipeline.batch_predict import resolve_predictor


class _DummyPredictor:
    def __init__(self, kind: str, cfg: dict):
        self.kind = kind
        self.cfg = cfg


def _make_recording_build_predictor(calls: list[tuple[str, dict]]):
    """`build_predictor(kind, **cfg)`를 대신해 호출을 기록하고 더미를 돌려준다."""

    def _build(kind: str, **cfg):
        calls.append((kind, cfg))
        return _DummyPredictor(kind, cfg)

    return _build


def _make_artifact(models_dir: Path, name: str, model_kind: str | None) -> Path:
    """`meta.json`만 있는 가짜 아티팩트 폴더. `model_kind=None`이면 키 자체를 뺀다(구 아티팩트 흉내)."""
    art = models_dir / name
    art.mkdir()
    meta = {} if model_kind is None else {"model_kind": model_kind}
    (art / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return art


def _settings(models_dir: Path, *, lgbm_artifact: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        crowd_models_dir=models_dir,
        crowd_lgbm_artifact=lgbm_artifact,
        crowd_dl_artifact="dl_gru_s14_noev_s42_20260914-1358",
        crowd_llm_api_key=None,
        crowd_llm_model=None,
    )


def test_pinned_artifact_used_by_auto_and_lightgbm(tmp_path, monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(batch_predict, "build_predictor", _make_recording_build_predictor(calls))
    pinned_name = "festival_selflag_d1sd_d7_resid_masked-stack_20260917-1113"
    pinned = _make_artifact(tmp_path, pinned_name, "lightgbm")
    # 이름 정렬에서 고정 폴더보다 뒤에 오는 폴더를 하나 더 둬 "고정"이 이름 정렬을 이기는지 본다.
    _make_artifact(tmp_path, "zzz_decoy_20261231-2359", "lightgbm")
    settings = _settings(tmp_path, lgbm_artifact=pinned_name)

    auto_predictor = resolve_predictor("auto", panel_train=None, settings=settings)
    lightgbm_predictor = resolve_predictor("lightgbm", panel_train=None, settings=settings)

    assert auto_predictor.cfg["artifact_dir"] == pinned
    assert lightgbm_predictor.cfg["artifact_dir"] == pinned
    assert [kind for kind, _ in calls] == ["lightgbm", "lightgbm"]


def test_pinned_artifact_missing_raises_file_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_predict, "build_predictor", _make_recording_build_predictor([]))
    settings = _settings(
        tmp_path, lgbm_artifact="festival_selflag_d1sd_d7_resid_masked-stack_20260917-1113"
    )

    with pytest.raises(FileNotFoundError, match="crowd_lgbm_artifact"):
        resolve_predictor("auto", panel_train=None, settings=settings)
    with pytest.raises(FileNotFoundError, match="crowd_lgbm_artifact"):
        resolve_predictor("lightgbm", panel_train=None, settings=settings)


def test_pinned_artifact_wrong_kind_raises_value_error(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_predict, "build_predictor", _make_recording_build_predictor([]))
    art = _make_artifact(tmp_path, "dl_gru_s14_noev_s42_20260914-1358", "dl")
    settings = _settings(tmp_path, lgbm_artifact=art.name)

    with pytest.raises(ValueError, match="model_kind"):
        resolve_predictor("auto", panel_train=None, settings=settings)
    with pytest.raises(ValueError, match="model_kind"):
        resolve_predictor("lightgbm", panel_train=None, settings=settings)


def test_unpinned_falls_back_to_latest_artifact_name_sort(tmp_path, monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(batch_predict, "build_predictor", _make_recording_build_predictor(calls))
    _make_artifact(tmp_path, "festival_selflag_d1sd_d7_resid_20260913-0340", "lightgbm")
    latest = _make_artifact(
        tmp_path, "festival_selflag_d1sd_d7_resid_masked-stack_20260917-1113", "lightgbm"
    )
    _make_artifact(tmp_path, "dl_gru_s14_noev_s42_20260914-1358", "dl")
    settings = _settings(tmp_path, lgbm_artifact=None)

    predictor = resolve_predictor("auto", panel_train=None, settings=settings)

    assert predictor.cfg["artifact_dir"] == latest


def test_unpinned_no_artifacts_auto_falls_back_to_lookup(tmp_path, monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(batch_predict, "build_predictor", _make_recording_build_predictor(calls))
    settings = _settings(tmp_path, lgbm_artifact=None)

    predictor = resolve_predictor("auto", panel_train="dummy_panel", settings=settings)

    assert predictor.kind == "lookup"
    assert calls == [("lookup", {"train_panel": "dummy_panel"})]
