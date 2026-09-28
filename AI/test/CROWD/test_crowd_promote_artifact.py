"""`promote_artifact` — 실험 아티팩트를 `models/CROWD/`로 복사하는 CLI(200 B부).

torch·lightgbm 없이도 도는 순수 파일 시스템 테스트다 — 아티팩트는 `meta.json` + 빈 모델 파일로
흉내 낸다. `get_settings()`는 부르지 않고 `SimpleNamespace` 스텁을 넘긴다
(`test_crowd_dl_artifact_resolve.py`와 같은 패턴).
"""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from app.CROWD.pipeline.promote_artifact import (
    copy_artifact,
    run,
    validate_artifact,
)


def _settings(models_dir, lgbm=None, dl=None) -> SimpleNamespace:
    return SimpleNamespace(
        crowd_models_dir=models_dir, crowd_lgbm_artifact=lgbm, crowd_dl_artifact=dl
    )


def _lgbm_artifact(root, name: str, *, n_train_rows=100, masking=None) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "lookup.parquet").write_bytes(b"")
    (d / "model_boarding.txt").write_bytes(b"")
    (d / "model_alighting.txt").write_bytes(b"")
    meta = {
        "feature_set": "festival_selflag_d1sd_d7_resid",
        "train_start": "2024-01-01",
        "train_end": "2024-12-31",
        "n_train_rows": n_train_rows,
        "created_at": "20260918-0000",
        "model_files": {
            "boarding": {"__all__": "model_boarding.txt"},
            "alighting": {"__all__": "model_alighting.txt"},
        },
    }
    if masking:
        meta["training"] = {"masking": masking}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _dl_artifact(root, name: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    for fname in ("model.pt", "scale.parquet", "event_stats.parquet", "lookup.parquet"):
        (d / fname).write_bytes(b"")
    meta = {
        "model_kind": "dl",
        "model": "gru",
        "splits": {"train": ["2024-01-01", "2024-10-31"]},
        "n_train_samples": 1234,
        "created_at": "20260918-0001",
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _args(src, dst_root=None, name=None, force=False) -> argparse.Namespace:
    return argparse.Namespace(src=str(src), dst_root=dst_root, name=name, force=force)


# ── kind 감지 ──
def test_validate_artifact_detects_lightgbm_when_model_kind_key_is_absent(tmp_path):
    _lgbm_artifact(tmp_path, "lgbm_a")
    kind, meta = validate_artifact(tmp_path / "lgbm_a")
    assert kind == "lightgbm"
    assert meta["feature_set"] == "festival_selflag_d1sd_d7_resid"


def test_validate_artifact_detects_dl_from_model_kind(tmp_path):
    _dl_artifact(tmp_path, "dl_a")
    kind, meta = validate_artifact(tmp_path / "dl_a")
    assert kind == "dl"
    assert meta["model"] == "gru"


def test_validate_artifact_missing_model_file_raises_system_exit(tmp_path):
    _lgbm_artifact(tmp_path, "lgbm_b")
    (tmp_path / "lgbm_b" / "model_alighting.txt").unlink()
    with pytest.raises(SystemExit, match="model_alighting.txt"):
        validate_artifact(tmp_path / "lgbm_b")


def test_validate_artifact_missing_meta_raises_system_exit(tmp_path):
    d = tmp_path / "no_meta"
    d.mkdir()
    with pytest.raises(SystemExit, match="meta.json"):
        validate_artifact(d)


def test_validate_artifact_dl_missing_model_pt_raises_system_exit(tmp_path):
    _dl_artifact(tmp_path, "dl_b")
    (tmp_path / "dl_b" / "model.pt").unlink()
    with pytest.raises(SystemExit, match="model.pt"):
        validate_artifact(tmp_path / "dl_b")


# ── 복사 ──
def test_copy_artifact_success(tmp_path):
    src_root = tmp_path / "src"
    _lgbm_artifact(src_root, "lgbm_ok")
    dst_root = tmp_path / "dst"
    settings = _settings(dst_root, lgbm=None)
    dst = copy_artifact(
        src_root / "lgbm_ok", dst_root, "lgbm_ok", "lightgbm", settings, force=False
    )
    assert dst == dst_root / "lgbm_ok"
    assert (dst / "lookup.parquet").exists()
    assert (dst / "meta.json").exists()


def test_copy_artifact_refuses_existing_destination_without_force(tmp_path):
    src_root = tmp_path / "src"
    _lgbm_artifact(src_root, "lgbm_c")
    dst_root = tmp_path / "dst"
    (dst_root / "lgbm_c").mkdir(parents=True)
    settings = _settings(dst_root, lgbm=None)
    with pytest.raises(SystemExit, match="이미 있다"):
        copy_artifact(src_root / "lgbm_c", dst_root, "lgbm_c", "lightgbm", settings, force=False)


def test_copy_artifact_refuses_overwriting_pinned_artifact_even_with_force(tmp_path):
    src_root = tmp_path / "src"
    _lgbm_artifact(src_root, "lgbm_pinned")
    dst_root = tmp_path / "dst"
    (dst_root / "lgbm_pinned").mkdir(parents=True)
    settings = _settings(dst_root, lgbm="lgbm_pinned")
    with pytest.raises(SystemExit, match="배포 중인 아티팩트"):
        copy_artifact(
            src_root / "lgbm_pinned", dst_root, "lgbm_pinned", "lightgbm", settings, force=True
        )


def test_copy_artifact_force_overwrites_non_pinned_destination(tmp_path):
    src_root = tmp_path / "src"
    _lgbm_artifact(src_root, "lgbm_d")
    dst_root = tmp_path / "dst"
    stale = dst_root / "lgbm_d"
    stale.mkdir(parents=True)
    (stale / "stale.txt").write_bytes(b"old")
    settings = _settings(dst_root, lgbm="다른_고정_이름")
    dst = copy_artifact(src_root / "lgbm_d", dst_root, "lgbm_d", "lightgbm", settings, force=True)
    assert (dst / "lookup.parquet").exists()
    assert not (dst / "stale.txt").exists()  # 강제 교체는 옛 내용을 지운다


def test_copy_artifact_dl_kind_checks_dl_pin_not_lgbm_pin(tmp_path):
    src_root = tmp_path / "src"
    _dl_artifact(src_root, "dl_pinned")
    dst_root = tmp_path / "dst"
    (dst_root / "dl_pinned").mkdir(parents=True)
    # lightgbm 고정값이 우연히 같은 이름이어도 dl 검사에는 영향이 없어야 한다
    settings = _settings(dst_root, lgbm="dl_pinned", dl="다른_dl")
    dst = copy_artifact(src_root / "dl_pinned", dst_root, "dl_pinned", "dl", settings, force=True)
    assert (dst / "model.pt").exists()


# ── run() 전체 흐름 ──
def test_run_end_to_end_copies_and_reports(tmp_path, capsys):
    src_root = tmp_path / "src"
    _lgbm_artifact(src_root, "festival_x_20260918-0000", masking={"mode": "stack"})
    dst_root = tmp_path / "dst"
    settings = _settings(dst_root, lgbm=None, dl=None)

    args = _args(src_root / "festival_x_20260918-0000", dst_root=str(dst_root))
    dst = run(args, settings=settings)

    assert dst == dst_root / "festival_x_20260918-0000"
    assert (dst / "meta.json").exists()
    out = capsys.readouterr().out
    assert "crowd_lgbm_artifact" in out
    assert "체크리스트" in out


def test_run_uses_settings_models_dir_when_dst_root_omitted(tmp_path):
    src_root = tmp_path / "src"
    _dl_artifact(src_root, "dl_default_dst")
    dst_root = tmp_path / "dst"
    settings = _settings(dst_root, dl=None)

    args = _args(src_root / "dl_default_dst")
    dst = run(args, settings=settings)
    assert dst == dst_root / "dl_default_dst"


def test_run_custom_name_overrides_src_folder_name(tmp_path):
    src_root = tmp_path / "src"
    _lgbm_artifact(src_root, "raw_name")
    dst_root = tmp_path / "dst"
    settings = _settings(dst_root)

    args = _args(src_root / "raw_name", dst_root=str(dst_root), name="renamed")
    dst = run(args, settings=settings)
    assert dst == dst_root / "renamed"
    assert (dst / "lookup.parquet").exists()
