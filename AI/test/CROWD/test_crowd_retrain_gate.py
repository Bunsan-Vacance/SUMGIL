"""챔피언·챌린저 게이트(`retrain/gate.py`) — 합성 데이터로 채택/기각·sanity·모드·등록을 확인한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.retrain import gate
from app.CROWD.pipeline.retrain.common import SCORE_META_NAME, SCORE_PARQUET_NAME, write_json

N_BOOT = 200
SIGMA = 10.0


def _frame(
    cand_scale: float = 0.5,
    lookup_scale: float = 3.0,
    seed: int = 0,
    availability: bool = False,
    bad_lookup_group: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """날짜 40일 × 역 5 × 슬롯 4. 챔피언 오차 σ, 후보 오차 σ·cand_scale, lookup 오차 σ·3."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-08-01", periods=40)
    index = pd.MultiIndex.from_product([dates, range(1, 6), range(4)], names=gate.KEY)
    base = index.to_frame(index=False)
    n = len(base)
    champ, cand = base.copy(), base.copy()
    avail = np.where(base["date"].dt.day % 2 == 0, "full", "partial")
    for target in gate.TARGETS:
        actual = rng.uniform(100, 1000, n)
        for frame in (champ, cand):
            frame[f"{target}_actual"] = actual
        champ[f"{target}_pred"] = actual + rng.normal(0, SIGMA, n)
        cand[f"{target}_pred"] = actual + rng.normal(0, SIGMA * cand_scale, n)
        lookup_err = rng.normal(0, SIGMA * lookup_scale, n)
        if bad_lookup_group is not None:
            # 해당 가용성에서는 lookup이 후보 예측보다 더 정확하다.
            lookup_err = np.where(
                avail == bad_lookup_group, rng.normal(0, SIGMA * 0.1, n), lookup_err
            )
        for frame in (champ, cand):
            frame[f"{target}_lookup"] = actual + lookup_err
    if availability:
        champ["availability"] = avail
        cand["availability"] = avail
    return cand, champ


def test_clearly_better_candidate_is_accepted():
    cand, champ = _frame(cand_scale=0.5)
    res = gate.evaluate_gate(cand, champ, n_boot=N_BOOT, seed=1)
    assert res["accept"] is True, res["reasons"]
    assert res["reasons"] == []
    for target in gate.TARGETS:
        stat = res["targets"][target]["vs_champion"]
        assert stat["point"] > 0
        assert stat["ci_low"] > gate.CI_LOWER_MIN_PP
    assert res["n_dates"] == 40
    assert res["n_rows"] == 40 * 5 * 4


def test_clearly_worse_candidate_is_rejected():
    cand, champ = _frame(cand_scale=2.0)
    res = gate.evaluate_gate(cand, champ, n_boot=N_BOOT, seed=1)
    assert res["accept"] is False
    assert any("점추정" in r for r in res["reasons"])
    assert res["targets"]["boarding"]["vs_champion"]["point"] < gate.POINT_MIN_PP


def test_worse_than_lookup_in_one_availability_is_rejected():
    cand, champ = _frame(cand_scale=0.5, availability=True, bad_lookup_group="partial")
    res = gate.evaluate_gate(cand, champ, n_boot=N_BOOT, seed=1)
    assert set(res["by_availability"]) == {"full", "partial"}
    assert res["accept"] is False
    assert any("partial" in r and "lookup" in r for r in res["reasons"])
    assert not any("가용성 full" in r for r in res["reasons"])
    # 챔피언 대비로는 좋으므로 점추정 사유는 없다.
    assert not any("점추정" in r for r in res["reasons"])


def test_availability_grouping_accepts_when_all_beat_lookup():
    cand, champ = _frame(cand_scale=0.5, availability=True)
    res = gate.evaluate_gate(cand, champ, n_boot=N_BOOT, seed=1)
    assert res["accept"] is True, res["reasons"]
    weights = sum(slot["weight"] for slot in res["by_availability"].values())
    assert abs(weights - 1.0) < 1e-9
    assert np.isfinite(res["targets"]["boarding"]["weighted_point"])


def test_nan_injection_fails_sanity():
    cand, champ = _frame(cand_scale=0.5)
    rng = np.random.default_rng(7)
    hit = rng.random(len(cand)) < 0.05
    cand.loc[hit, "boarding_pred"] = np.nan
    res = gate.evaluate_gate(cand, champ, n_boot=N_BOOT, seed=1)
    assert res["accept"] is False
    assert any(r.startswith("sanity") and "NaN" in r for r in res["reasons"])
    assert res["sanity"]["nan_ratio_cand"] > gate.MAX_NAN_RATIO


def test_feature_column_mismatch_fails_sanity():
    cand, champ = _frame(cand_scale=0.5)
    res = gate.evaluate_gate(
        cand,
        champ,
        n_boot=N_BOOT,
        seed=1,
        feature_columns_cand=["a", "b"],
        feature_columns_champ=["a", "c"],
    )
    assert res["accept"] is False
    assert any("피처" in r for r in res["reasons"])


def test_insufficient_dates_raises():
    cand, champ = _frame()
    few = cand["date"] < cand["date"].min() + pd.Timedelta(days=3)
    try:
        gate.evaluate_gate(cand[few], champ[few], n_boot=N_BOOT)
    except gate.GateInputError:
        return
    raise AssertionError("날짜 부족인데 예외가 나지 않았다")


def _write_score_dir(root: Path, rows: pd.DataFrame) -> None:
    for day, sub in rows.groupby("date"):
        out = root / f"dt={day:%Y-%m-%d}"
        out.mkdir(parents=True)
        sub.to_parquet(out / SCORE_PARQUET_NAME, index=False)
        write_json(out / SCORE_META_NAME, {"target_date": f"{day:%Y-%m-%d}"})


def test_gate_shadow_reads_dirs_and_writes_json(tmp_path):
    cand, champ = _frame(cand_scale=0.5, availability=True)
    direct = gate.evaluate_gate(cand, champ, n_boot=N_BOOT, seed=1)
    _write_score_dir(tmp_path / "champ", champ)
    _write_score_dir(tmp_path / "shadow", cand)

    res = gate.gate_shadow(tmp_path / "champ", tmp_path / "shadow", days=40, n_boot=N_BOOT, seed=1)
    assert res["mode"] == "shadow"
    assert res["accept"] == direct["accept"] is True
    assert res["window"] == ["2026-08-01", "2026-09-09"]
    for target in gate.TARGETS:
        assert (
            res["targets"][target]["vs_champion"]["point"]
            == direct["targets"][target]["vs_champion"]["point"]
        )

    recent = gate.gate_shadow(tmp_path / "champ", tmp_path / "shadow", days=28, n_boot=N_BOOT)
    assert recent["n_dates"] == 28

    out = gate.write_gate_result(res, tmp_path / "gate.json")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["accept"] is True
    assert "decided_at" in doc
    assert doc["targets"]["boarding"]["vs_champion"]["point"] > 0


def test_gate_shadow_without_overlap_is_insufficient(tmp_path):
    cand, champ = _frame()
    _write_score_dir(tmp_path / "champ", champ[champ["date"] < "2026-08-10"])
    _write_score_dir(tmp_path / "shadow", cand[cand["date"] >= "2026-08-20"])
    try:
        gate.gate_shadow(tmp_path / "champ", tmp_path / "shadow", n_boot=N_BOOT)
    except gate.GateInputError:
        return
    raise AssertionError("겹치는 날짜가 없는데 예외가 나지 않았다")


def test_register_shadow_candidate_dedups_and_skips_rejected(tmp_path):
    path = tmp_path / "shadow_candidates.json"
    cand, champ = _frame(cand_scale=0.5)
    ok = gate.evaluate_gate(cand, champ, n_boot=N_BOOT, seed=1)
    ok["mode"] = "holdout"

    assert gate.register_shadow_candidate(path, "lightgbm_20261001", ok) is True
    assert gate.register_shadow_candidate(path, "lightgbm_20261001", ok) is False
    assert gate.register_shadow_candidate(path, "lightgbm_20261002", ok) is True
    names = [c["artifact"] for c in json.loads(path.read_text(encoding="utf-8"))["candidates"]]
    assert names == ["lightgbm_20261001", "lightgbm_20261002"]

    assert gate.register_shadow_candidate(path, "rejected", {"accept": False}) is False
    assert len(json.loads(path.read_text(encoding="utf-8"))["candidates"]) == 2
