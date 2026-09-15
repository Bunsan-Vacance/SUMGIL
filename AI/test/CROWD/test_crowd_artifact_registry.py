"""`predictor.latest_artifact`의 계열 필터 — torch 없이도 도는 부분(144).

`--predictor auto`가 DL 아티팩트를 집어가면 운영 기본값이 조용히 바뀐다. 그 방어가 여기 있고,
torch가 필요한 DL 예측기 동작은 `test_crowd_dl_predictor.py`에 따로 둔다(CI는 torch가 없다).
"""

from __future__ import annotations

import json

from app.CROWD.pipeline.predictor import artifact_kind, latest_artifact


def _artifact(root, name: str, meta: dict | None):
    d = root / name
    d.mkdir(parents=True)
    if meta is not None:
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return d


def test_latest_artifact_filters_by_model_kind(tmp_path):
    _artifact(tmp_path, "festival_selflag_d1sd_d7_resid_20260913-0340", {"feature_set": "x"})
    _artifact(tmp_path, "festival_selflag_d1sd_d7_resid_20260914-0100", {"model_kind": "lightgbm"})
    dl = _artifact(tmp_path, "dl_gru_s14_20260914-0949", {"model_kind": "dl"})

    # 필터 없이는 계열과 무관하게 폴더명 정렬 최신 — 계열이 섞이면 이름 운에 맡겨진다
    assert latest_artifact(tmp_path) == max([dl, *tmp_path.iterdir()], key=lambda q: q.name)
    assert latest_artifact(tmp_path, kind="dl") == dl
    assert latest_artifact(tmp_path, kind="lightgbm").name.endswith("20260914-0100")


def test_artifact_kind_defaults_to_lightgbm_and_prefix_still_works(tmp_path):
    old = _artifact(tmp_path, "festival_all_derived_resid_20260911-1518", {"feature_set": "x"})
    _artifact(tmp_path, "dl_gru_s14_20260914-0949", {"model_kind": "dl"})
    assert artifact_kind(old) == "lightgbm"  # 144 이전 아티팩트에는 model_kind가 없다
    assert artifact_kind(tmp_path / "없는폴더") == "unknown"
    assert latest_artifact(tmp_path, prefix="festival_", kind="lightgbm") == old


def test_latest_artifact_ignores_dirs_without_meta_and_empty_dir(tmp_path):
    (tmp_path / "dl_gru_s14_99999999-9999").mkdir()  # meta.json 없음
    art = _artifact(tmp_path, "dl_gru_s14_20260914-0949", {"model_kind": "dl"})
    assert latest_artifact(tmp_path, kind="dl") == art
    assert latest_artifact(tmp_path / "없음") is None
