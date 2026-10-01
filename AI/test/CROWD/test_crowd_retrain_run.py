"""재학습 러너(`retrain/run.py`) — 조건 분기·단계 순서·실패 중단·보존 정책."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.CROWD.pipeline.retrain import run as runner

# 2026-10-02(금) 22:00 KST — 첫 일요일(10-04) 전이라 R3는 due가 아니다.
NOW = pd.Timestamp("2026-10-02 22:00", tz="Asia/Seoul")
RUN_ID = "20261002-2200"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """경로 상수를 tmp로, subprocess를 가짜로 바꾼다. `calls`에 명령이 쌓이고 `rcs`로 rc를 지정."""
    mon = tmp_path / "data" / "CROWD" / "monitoring"
    mon.mkdir(parents=True)
    monkeypatch.setattr(runner, "AI_ROOT", tmp_path)
    monkeypatch.setattr(runner, "REQUEST_PATH", mon / "retrain_request.json")
    monkeypatch.setattr(runner, "STATE_PATH", mon / "retrain_state.json")
    monkeypatch.setattr(runner, "SCORE_DIR", mon / "score_daily")
    monkeypatch.setattr(runner, "now_kst", lambda: NOW)
    monkeypatch.setattr(runner, "resolve_champion", lambda: tmp_path / "models" / "CROWD" / "champ")
    monkeypatch.setattr(runner, "_systemctl_state", lambda unit: None)
    monkeypatch.setattr(runner, "_send_discord", lambda message: "skipped")

    calls: list[list[str]] = []
    rcs: dict[str, int] = {}

    def fake_exec(cmd, cwd, env_):
        calls.append(list(cmd))
        joined = " ".join(cmd)
        for key, rc in rcs.items():
            if key in joined:
                return rc
        return 0

    monkeypatch.setattr(runner, "_exec", fake_exec)

    class Env:
        pass

    e = Env()
    e.root, e.mon, e.calls, e.rcs = tmp_path, mon, calls, rcs
    e.state = lambda: json.loads((mon / "retrain_state.json").read_text(encoding="utf-8"))
    return e


def step_names(state: dict) -> list[str]:
    return [s["step"] for s in state["runs"][-1]["steps"]]


def test_요청_없고_R3_아니면_99로_skip하고_사유를_남긴다(env):
    rc = runner.main(["--skip-window", "--run", RUN_ID])
    assert rc == 99
    last = env.state()["runs"][-1]
    assert last["status"] == "skipped"
    assert last["steps"][0]["step"] == "short_circuit"
    assert last["steps"][0]["rc"] == 99
    assert "재학습 요청 없음" in last["steps"][0]["detail"]["reason"]
    assert env.calls == []


def test_force_dry_run은_열_단계를_순서대로_기록한다(env):
    rc = runner.main(["--force", "--skip-window", "--dry-run", "--run", RUN_ID])
    assert rc == 0
    last = env.state()["runs"][-1]
    assert [s["step"] for s in last["steps"]] == list(
        [
            "short_circuit",
            "guard",
            "build_panel",
            "to_wide",
            "events",
            "train",
            "gate",
            "report",
            "notify",
            "mark_done",
        ]
    )
    cmds = {s["step"]: s["detail"].get("cmd", "") for s in last["steps"]}
    assert "crowd_panel_rebuild" in cmds["build_panel"]
    assert "--verify-against" in cmds["build_panel"]
    assert "build_crowd_panel" in cmds["to_wide"]
    assert "--end 2026-10-01" in cmds["to_wide"]
    assert "map_events_to_stations" in cmds["events"]
    assert "--derived-cache" in cmds["train"]
    assert "--out-root" in cmds["train"]
    assert "--split-date 2026-09-04" in cmds["train"]  # D-28
    assert "gate holdout" in cmds["gate"]
    assert "--register" in cmds["gate"]
    assert env.calls == []  # dry-run은 실행하지 않는다


def test_build_panel_실패면_이후_단계를_돌리지_않는다(env):
    env.rcs["crowd_panel_rebuild"] = 1
    rc = runner.main(["--force", "--skip-window", "--run", RUN_ID])
    assert rc == 1
    state = env.state()
    assert step_names(state) == ["short_circuit", "guard", "build_panel"]
    assert state["runs"][-1]["status"] == "failed"
    assert len(env.calls) == 1


def test_gate_기각_rc3도_report_notify_mark_done까지_진행한다(env):
    env.rcs["retrain.gate"] = 3
    rc = runner.main(["--force", "--skip-window", "--run", RUN_ID])
    assert rc == 0
    state = env.state()
    assert step_names(state)[-4:] == ["gate", "report", "notify", "mark_done"]
    assert state["runs"][-1]["status"] == "done"
    report = env.root / "models" / "CROWD" / "_experiments" / "auto" / f"auto_{RUN_ID}"
    assert "기각" in (report / "RETRAIN_REPORT.md").read_text(encoding="utf-8")


def test_gate_입력부족_rc2는_실패다(env):
    env.rcs["retrain.gate"] = 2
    rc = runner.main(["--force", "--skip-window", "--run", RUN_ID])
    assert rc == 2
    assert step_names(env.state())[-1] == "gate"


def test_야간창_밖이면_99로_skip한다(env, monkeypatch):
    monkeypatch.setattr(
        runner, "now_kst", lambda: pd.Timestamp("2026-10-02 14:00", tz="Asia/Seoul")
    )
    rc = runner.main(["--force", "--run", RUN_ID])
    assert rc == 99
    last = env.state()["runs"][-1]
    assert last["steps"][-1]["step"] == "guard"
    assert "야간창" in last["steps"][-1]["detail"]["reason"]
    assert env.calls == []


def test_야간창_판정_경계(env):
    def at(hhmm):
        return runner.in_night_window(pd.Timestamp(f"2026-10-02 {hhmm}", tz="Asia/Seoul"))[0]

    assert at("21:00") and at("23:59") and at("00:10") and at("07:59")
    assert not at("08:00") and not at("20:59")
    assert not at("03:00") and not at("03:29") and at("03:30")


def test_유효한_요청_파일이면_진행하고_mark_done이_done으로_바꾼다(env):
    from app.CROWD.pipeline.retrain import drift

    drift.write_request(
        runner.REQUEST_PATH,
        rule="R3",
        reason="테스트",
        target_date=pd.Timestamp("2026-10-02"),
        now=NOW,
    )
    rc = runner.main(["--skip-window", "--run", RUN_ID])
    assert rc == 0
    assert not runner.REQUEST_PATH.exists()
    assert (env.mon / "retrain_request.done.json").exists()
    assert env.state()["last_candidate_date"] == "2026-10-02"


def test_보존_정책은_등록된_후보를_지우지_않는다(env):
    proc = env.root / "data" / "CROWD" / "processed" / "auto"
    exp = env.root / "models" / "CROWD" / "_experiments" / "auto"
    old_runs = [f"2026090{i}-2200" for i in range(1, 7)]  # 6개
    for r in old_runs:
        (proc / r).mkdir(parents=True)
        (exp / f"auto_{r}").mkdir(parents=True)
    (env.mon / "shadow_candidates.json").write_text(
        json.dumps({"candidates": [{"artifact": f"auto_{old_runs[0]}"}]}), encoding="utf-8"
    )
    removed = runner.apply_retention(4, RUN_ID)
    # 최신 4개(이번 run은 폴더가 없어 목록에 없음) → 오래된 것부터 지우되 등록 후보(첫 번째)는 보존
    assert old_runs[0] not in removed
    assert (exp / f"auto_{old_runs[0]}").exists()
    assert (proc / old_runs[0]).exists()
    assert not (exp / f"auto_{old_runs[1]}").exists()
    assert (exp / f"auto_{old_runs[-1]}").exists()
    assert removed == [old_runs[1]]  # 삭제 후보 2개 중 등록된 하나는 보존
