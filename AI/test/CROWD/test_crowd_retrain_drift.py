"""재학습 루프 드리프트(`retrain/drift.py`) — R0·R1'·R3 규칙과 요청 파일 수명."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app.CROWD.pipeline.retrain import drift

TODAY = pd.Timestamp("2026-10-04")  # 10월 첫 일요일


def make_rows(model_scale: float, n_days: int = 14, availability: str = "full", seed: int = 0):
    """lookup 오차는 ±3 고정, 모델 오차는 `model_scale`배. 날짜마다 약간의 노이즈."""
    rng = np.random.default_rng(seed)
    frames = []
    for d in pd.date_range(TODAY - pd.Timedelta(days=n_days), periods=n_days):
        actual = rng.uniform(100, 200, size=40)
        noise = rng.normal(0, 0.3, size=40)
        frame = pd.DataFrame({"date": d, "availability": availability}, index=range(40))
        for target in ("boarding", "alighting"):
            frame[f"{target}_actual"] = actual
            frame[f"{target}_pred"] = actual + model_scale * (3.0 + noise)
            frame[f"{target}_lookup"] = actual + 3.0 + rng.normal(0, 0.3, size=40)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def make_scores(root, days: list[pd.Timestamp]) -> None:
    for d in days:
        path = root / f"dt={d:%Y-%m-%d}"
        path.mkdir(parents=True)
        (path / "part.meta.json").write_text(json.dumps({"target_date": f"{d:%Y-%m-%d}"}))
        pd.DataFrame({"date": [d]}).to_parquet(path / "part.parquet")


# ── R3 ──
def test_first_sunday():
    assert drift.first_sunday(2026, 10) == pd.Timestamp("2026-10-04")
    assert drift.first_sunday(2026, 11) == pd.Timestamp("2026-11-01")
    assert drift.first_sunday(2026, 12) == pd.Timestamp("2026-12-06")
    assert drift.is_first_sunday(pd.Timestamp("2026-10-04"))
    assert not drift.is_first_sunday(pd.Timestamp("2026-10-11"))
    assert not drift.is_first_sunday(pd.Timestamp("2026-10-05"))


def test_r3_due_only_when_first_sunday_and_enough_days():
    days = list(pd.date_range("2026-09-01", periods=25))
    assert drift.r3_calendar_due(TODAY, None, days)["due"] is True
    # 첫 일요일이 아니면 아니다
    not_sunday = drift.r3_calendar_due(pd.Timestamp("2026-10-05"), None, days)
    assert not_sunday["due"] is False
    assert not_sunday["is_first_sunday"] is False
    # 신규 채점일이 모자라면 아니다
    assert drift.r3_calendar_due(TODAY, None, days[:19])["due"] is False
    # 마지막 후보 이후 날짜만 센다
    state = {"last_candidate_date": "2026-09-10"}
    res = drift.r3_calendar_due(TODAY, state, days)
    assert res["new_scored_days"] == 15
    assert res["due"] is False


# ── R0 ──
def test_r0_hold_when_more_than_seven_missing(tmp_path):
    ok_days = list(pd.date_range(TODAY - pd.Timedelta(days=28), periods=21))
    make_scores(tmp_path, ok_days)  # 28일 중 21일 존재 → 결손 7일
    res = drift.r0_data_hold(tmp_path, TODAY)
    assert res["missing_days"] == 7
    assert res["hold"] is False
    assert drift.r0_data_hold(tmp_path / "none", TODAY)["hold"] is True

    few = tmp_path / "few"
    make_scores(few, ok_days[:20])  # 결손 8일
    assert drift.r0_data_hold(few, TODAY)["hold"] is True


# ── R1' ──
def test_r1_alert_when_model_clearly_worse():
    res = drift.r1_performance_alert(make_rows(model_scale=3.0), n_boot=200)
    assert len(res["alerts"]) == 2
    alert = res["alerts"][0]
    assert alert["rule"] == "R1'"
    assert alert["ci_high"] < 0
    assert alert["availability"] == "full"


def test_r1_no_alert_when_clearly_better():
    res = drift.r1_performance_alert(make_rows(model_scale=0.2), n_boot=200)
    assert res["alerts"] == []
    assert len(res["groups"]) == 2
    assert all(g["point"] > 0 for g in res["groups"])


def test_r1_skips_small_group_and_baseline_drop():
    rows = pd.concat(
        [make_rows(0.2, n_days=14), make_rows(0.2, n_days=5, availability="no_lag")],
        ignore_index=True,
    )
    res = drift.r1_performance_alert(rows, n_boot=100)
    assert {s["availability"] for s in res["skipped"]} == {"no_lag"}
    point = res["groups"][0]["point"]
    base = {"full": {"boarding": point + 20.0, "alighting": point}}
    res2 = drift.r1_performance_alert(rows, n_boot=100, baseline=base)
    assert [(a["availability"], a["target"]) for a in res2["alerts"]] == [("full", "boarding")]


def test_r1_empty_rows():
    res = drift.r1_performance_alert(pd.DataFrame())
    assert res == {"alerts": [], "skipped": [], "groups": []}


# ── 요청 파일 ──
def test_request_write_read_valid_and_expired(tmp_path):
    path = tmp_path / "retrain_request.json"
    now = pd.Timestamp("2026-10-04T09:00:00+09:00")
    req = drift.write_request(path, rule="R3", reason="r", target_date=TODAY, now=now)
    assert set(req) == {"rule", "reason", "date", "created_at", "expires"}
    assert req["date"] == "2026-10-04"

    got, status = drift.read_request(path, now + pd.Timedelta(days=6))
    assert status == "valid"
    assert got["rule"] == "R3"
    assert path.exists()

    got, status = drift.read_request(path, now + pd.Timedelta(days=7, hours=1))
    assert status == "expired"
    assert not path.exists()
    assert (tmp_path / "retrain_request.expired.json").exists()

    assert drift.read_request(path, now) == (None, "none")


def test_expired_overwrites_previous_expired(tmp_path):
    path = tmp_path / "retrain_request.json"
    now = pd.Timestamp("2026-10-04T09:00:00+09:00")
    for _ in range(2):
        drift.write_request(path, rule="R3", reason="r", target_date=TODAY, now=now)
        drift.read_request(path, now + pd.Timedelta(days=8))
    assert (tmp_path / "retrain_request.expired.json").exists()


def test_mark_done_renames(tmp_path):
    path = tmp_path / "retrain_request.json"
    now = pd.Timestamp("2026-10-04T09:00:00+09:00")
    drift.write_request(path, rule="R3", reason="r", target_date=TODAY, now=now)
    done = drift.mark_done(path)
    assert done.name == "retrain_request.done.json"
    assert done.exists()
    assert not path.exists()


# ── 평가 ──
def test_evaluate_writes_latest_and_request_on_r3_due(tmp_path):
    score_root = tmp_path / "score_daily"
    make_scores(score_root, list(pd.date_range(TODAY - pd.Timedelta(days=25), periods=25)))
    monitoring = tmp_path

    result = drift.evaluate(TODAY, score_root=score_root, monitoring_dir=monitoring, n_boot=50)
    assert result["r0"]["hold"] is False
    assert result["r3"]["due"] is True
    assert result["request"]["written"] is True
    assert (monitoring / "retrain_request.json").exists()
    latest = json.loads((monitoring / "drift_latest.json").read_text(encoding="utf-8"))
    assert latest["r3"]["due"] is True
    assert latest["request"]["status"] == "valid"

    # 유효한 요청이 이미 있으면 다시 쓰지 않는다
    again = drift.evaluate(TODAY, score_root=score_root, monitoring_dir=monitoring, n_boot=50)
    assert again["request"]["written"] is False
    assert again["request"]["status"] == "valid"


def test_evaluate_r0_hold_skips_r1(tmp_path):
    result = drift.evaluate(
        TODAY, score_root=tmp_path / "score_daily", monitoring_dir=tmp_path, n_boot=50
    )
    assert result["r0"]["hold"] is True
    assert result["r1"]["skipped_reason"] == "R0 hold"
    assert result["r3"]["due"] is False
    assert not (tmp_path / "retrain_request.json").exists()
    assert (tmp_path / "drift_latest.json").exists()
