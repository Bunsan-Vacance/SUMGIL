"""재학습 러너 — systemd 타이머가 부르는 단일 진입점(Airflow 없음, 340 P4-2).

순서: short_circuit → guard → build_panel(Spark 롱) → to_wide(pandas) → events → train →
gate(holdout) → report → notify → mark_done. 단계마다 기존 CLI를 subprocess로 부르고
`{step, rc, sec, detail}`을 `retrain_state.json`의 `runs[-1].steps`에 쌓는다.

**자동 승격은 없다.** 후보는 `models/CROWD/_experiments/auto/auto_<run>/`에 남고, 게이트를
통과하면 `shadow_candidates.json`에만 등록된다. 서빙 아티팩트 교체는 사람이 한다.

종료 코드: 0 완료, 99 skip(정상 — 요청 없음·야간창 밖·수집 재처리 중), 그 외 실패 단계의 코드.
`gate` 단계는 rc 0(채택)·3(기각) 모두 정상으로 이어 가고 2(입력 부족)만 실패다.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.CROWD.pipeline.retrain import drift
from app.CROWD.pipeline.retrain.common import (
    AI_ROOT,
    REQUEST_PATH,
    SCORE_DIR,
    STATE_PATH,
    atomic_write_text,
    load_deploy_stamp,
    now_kst,
    read_json,
    write_json,
)

# ── 상수 ──
NIGHT_START_HOUR = 21  # 야간창 21:00 ~ 익일 08:00 (KST)
NIGHT_END_HOUR = 8
EXCLUDE_START_MIN = 3 * 60  # 03:00 ~ 03:30 제외(bike-avg-batch·retention 겹침)
EXCLUDE_END_MIN = 3 * 60 + 30
MIN_FREE_GB = 10
TRAIN_START = "2024-01-01"
HOLDOUT_DAYS = 28
KEEP_RUNS = 4
MAX_STATE_RUNS = 60
REALTIME_UNIT = "bike-realtime-reprocess.service"
FEATURE_SET = "festival_selflag_d1sd_d7_resid"

EXIT_SKIP = 99
GATE_OK_CODES = (0, 3)


# ── 경로(AI_ROOT를 호출 시점에 읽는다 — 테스트가 바꿔 끼운다) ──
def processed_root() -> Path:
    return AI_ROOT / "data" / "CROWD" / "processed"


def interim_root() -> Path:
    return AI_ROOT / "data" / "CROWD" / "interim"


def experiments_root() -> Path:
    return AI_ROOT / "models" / "CROWD" / "_experiments" / "auto"


def candidates_path() -> Path:
    return AI_ROOT / "data" / "CROWD" / "monitoring" / "shadow_candidates.json"


@dataclass
class Ctx:
    """한 번의 실행이 공유하는 값."""

    run_id: str
    today: pd.Timestamp  # D (KST 날짜, 자정)
    now: pd.Timestamp
    python: str
    force: bool
    skip_window: bool
    full: bool
    dry_run: bool
    state: dict = field(default_factory=dict)
    rec: dict = field(default_factory=dict)
    request: dict | None = None
    gate_rc: int | None = None
    peak_rss_mb: float | None = None

    @property
    def split_date(self) -> str:
        return f"{self.today - pd.Timedelta(days=HOLDOUT_DAYS):%Y-%m-%d}"

    @property
    def end_date(self) -> str:
        return f"{self.today - pd.Timedelta(days=1):%Y-%m-%d}"

    @property
    def long_dir_rel(self) -> str:
        return f"data/CROWD/processed/auto/{self.run_id}"

    @property
    def long_rel(self) -> str:
        return f"{self.long_dir_rel}/panel_{self.run_id}.parquet"

    @property
    def wide_rel(self) -> str:  # processed 기준 상대경로
        return f"auto/{self.run_id}/panel_wide.parquet"

    @property
    def events_rel(self) -> str:
        return f"auto/{self.run_id}/events.parquet"

    @property
    def cache_rel(self) -> str:  # interim 기준 상대경로
        return f"auto/derived_{self.run_id}.parquet"

    @property
    def candidate_name(self) -> str:
        return f"auto_{self.run_id}"

    @property
    def candidate_dir(self) -> Path:
        return experiments_root() / self.candidate_name


# ── 상태 파일 ──
def _save_state(ctx: Ctx) -> None:
    write_json(STATE_PATH, ctx.state)


def _record(ctx: Ctx, step: str, rc: int, sec: float, detail) -> dict:
    result = {"step": step, "rc": int(rc), "sec": round(float(sec), 2), "detail": detail}
    ctx.rec["steps"].append(result)
    _save_state(ctx)
    cmd = detail.get("cmd") if isinstance(detail, dict) else None
    tail = f" cmd={cmd}" if cmd else ""
    print(f"[retrain] step={step} rc={rc} sec={result['sec']}{tail}", flush=True)
    return result


# ── subprocess ──
def _exec(cmd: list[str], cwd: Path, env: dict) -> int:
    """자식 프로세스를 돌리고 종료 코드를 돌려준다(출력은 그대로 흘려 보낸다). 테스트가 대체한다."""
    return subprocess.run(cmd, cwd=str(cwd), env=env, check=False).returncode


def _child_env() -> dict:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "TZ": "Asia/Seoul"}


def _py_cmd(ctx: Ctx, module: str, *args: str) -> list[str]:
    return [ctx.python, "-m", module, *args]


def _parse_max_rss_mb(text: str) -> float | None:
    """`/usr/bin/time -v` 출력의 `Maximum resident set size (kbytes): N`을 MB로."""
    m = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", text)
    return round(int(m.group(1)) / 1024, 1) if m else None


def _run_cmd(ctx: Ctx, step: str, cmd: list[str], *, measure_rss: bool = False) -> dict:
    """명령 한 개를 단계로 실행·기록한다. dry-run이면 실행하지 않고 명령 문자열만 남긴다."""
    shown = " ".join(cmd)
    if ctx.dry_run:
        return _record(ctx, step, 0, 0.0, {"cmd": shown, "dry_run": True})
    rss_file: Path | None = None
    real = cmd
    if measure_rss and platform.system() == "Linux" and os.path.exists("/usr/bin/time"):
        # GNU time은 -o 파일로 써야 자식의 stderr를 가리지 않는다.
        rss_file = STATE_PATH.with_name(f"rss_{ctx.run_id}.txt")
        rss_file.parent.mkdir(parents=True, exist_ok=True)
        real = ["/usr/bin/time", "-v", "-o", str(rss_file), *cmd]
    start = time.monotonic()
    rc = _exec(real, AI_ROOT, _child_env())
    sec = time.monotonic() - start
    detail: dict = {"cmd": shown}
    if measure_rss:
        peak = None
        if rss_file is not None and rss_file.exists():
            peak = _parse_max_rss_mb(rss_file.read_text(encoding="utf-8", errors="replace"))
            rss_file.unlink(missing_ok=True)
        ctx.peak_rss_mb = peak
        detail["peak_rss_mb"] = peak
    return _record(ctx, step, rc, sec, detail)


# ── 단계 1·2: 조건 ──
def in_night_window(now: pd.Timestamp) -> tuple[bool, str]:
    """KST 21:00~08:00 이고 03:00~03:30이 아니면 True."""
    minutes = now.hour * 60 + now.minute
    if EXCLUDE_START_MIN <= minutes < EXCLUDE_END_MIN:
        return False, f"제외 시간대 03:00~03:30 ({now:%H:%M})"
    if now.hour >= NIGHT_START_HOUR or now.hour < NIGHT_END_HOUR:
        return True, f"야간창 안 ({now:%H:%M})"
    return False, f"야간창(21:00~08:00) 밖 ({now:%H:%M})"


def short_circuit(ctx: Ctx) -> dict:
    """요청 파일(유효)·R3 due·`--force` 중 하나가 있어야 진행한다. 없으면 rc 99."""
    start = time.monotonic()
    request, status = drift.read_request(REQUEST_PATH, ctx.now)
    detail: dict = {"request_status": status, "force": ctx.force}
    trigger = None
    if status == "valid":
        ctx.request = request
        trigger = f"요청 파일({request.get('rule')}: {request.get('reason')})"
    else:
        r3 = drift.r3_calendar_due(ctx.today, ctx.state, drift.scored_dates(SCORE_DIR))
        detail["r3"] = r3
        last = ctx.state.get("last_candidate_date")
        same_month = bool(last) and pd.Timestamp(last).strftime("%Y-%m") == f"{ctx.today:%Y-%m}"
        if r3["due"] and same_month:
            detail["r3_skipped"] = f"이번 달({last}) 후보가 이미 있다"
        elif r3["due"]:
            trigger = f"R3 달력({r3['reason']})"
    if trigger is None and ctx.force:
        trigger = "--force"
    sec = time.monotonic() - start
    if trigger is None:
        detail["reason"] = "재학습 요청 없음 · R3 not due · --force 아님"
        return _record(ctx, "short_circuit", EXIT_SKIP, sec, detail)
    detail["trigger"] = trigger
    return _record(ctx, "short_circuit", 0, sec, detail)


def _systemctl_state(unit: str) -> str | None:
    """`systemctl is-active` 결과 문자열. systemctl이 없으면 None."""
    if shutil.which("systemctl") is None:
        return None
    proc = subprocess.run(
        ["systemctl", "is-active", unit], capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() or "unknown"


def guard(ctx: Ctx) -> dict:
    """야간창·수집 재처리 중복·디스크 여유를 본다. 창 밖·재처리 중이면 99, 디스크 부족은 1."""
    start = time.monotonic()
    detail: dict = {}
    if ctx.skip_window:
        detail["window"] = "--skip-window: 야간창 검사 생략"
    else:
        ok, why = in_night_window(ctx.now)
        detail["window"] = why
        if not ok:
            detail["reason"] = why
            return _record(ctx, "guard", EXIT_SKIP, time.monotonic() - start, detail)
    active = _systemctl_state(REALTIME_UNIT)
    detail["realtime_reprocess"] = active if active is not None else "systemctl 없음 — 통과"
    if active == "active":
        detail["reason"] = f"{REALTIME_UNIT} 실행 중"
        return _record(ctx, "guard", EXIT_SKIP, time.monotonic() - start, detail)
    free_gb = shutil.disk_usage(AI_ROOT).free / 1024**3
    detail["free_gb"] = round(free_gb, 1)
    if free_gb < MIN_FREE_GB:
        detail["reason"] = f"디스크 여유 {free_gb:.1f}GB < {MIN_FREE_GB}GB"
        return _record(ctx, "guard", 1, time.monotonic() - start, detail)
    return _record(ctx, "guard", 0, time.monotonic() - start, detail)


# ── 단계 3~7: subprocess ──
def build_panel(ctx: Ctx) -> dict:
    cmd = _py_cmd(
        ctx,
        "DATA_ENGINE.spark.jobs.crowd_panel_rebuild",
        "--out-root",
        ctx.long_dir_rel,
        "--run",
        ctx.run_id,
        "--base-panel",
        "data/CROWD/processed/crowd_panel_2024_2025.parquet",
        "--verify-against",
        "data/CROWD/interim/crowd_recent_ridership_long.parquet",
    )
    if ctx.full:
        cmd.append("--full")
    return _run_cmd(ctx, "build_panel", cmd)


def to_wide(ctx: Ctx) -> dict:
    # build_crowd_panel의 `--out`은 CROWD_PROCESSED / <값>이라 `auto/<run>/…` 상대경로가 먹는다
    # (부모 폴더는 build_panel이 만든 `auto/<run>/`). 혹시를 위해 부모를 미리 만든다.
    if not ctx.dry_run:
        (processed_root() / "auto" / ctx.run_id).mkdir(parents=True, exist_ok=True)
    cmd = _py_cmd(
        ctx,
        "DATA_ENGINE.eda.build_crowd_panel",
        "--long",
        ctx.long_rel,
        "--start",
        TRAIN_START,
        "--end",
        ctx.end_date,
        "--out",
        ctx.wide_rel,
    )
    return _run_cmd(ctx, "to_wide", cmd)


def events(ctx: Ctx) -> dict:
    print(
        "[retrain] 경고: 2026 축제 원천이 없으면 해당 구간 축제 건수는 0(=수집 안 됨)이다 "
        "- map_events_to_stations의 원천 범위 경고를 확인한다",
        flush=True,
    )
    cmd = _py_cmd(
        ctx,
        "DATA_ENGINE.eda.map_events_to_stations",
        "--panel",
        ctx.wide_rel,
        "--out",
        ctx.events_rel,
    )
    return _run_cmd(ctx, "events", cmd)


def train(ctx: Ctx) -> dict:
    if not ctx.dry_run:
        (interim_root() / "auto").mkdir(parents=True, exist_ok=True)
        experiments_root().mkdir(parents=True, exist_ok=True)
    cmd = _py_cmd(
        ctx,
        "app.CROWD.pipeline.train",
        "--panel",
        ctx.wide_rel,
        "--events",
        ctx.events_rel,
        "--derived-cache",
        ctx.cache_rel,
        "--feature-set",
        FEATURE_SET,
        "--mask-mode",
        "stack",
        "--split-date",
        ctx.split_date,
        "--out-root",
        "models/CROWD/_experiments/auto",
        "--name",
        ctx.candidate_name,
    )
    return _run_cmd(ctx, "train", cmd, measure_rss=True)


def resolve_champion() -> Path:
    """현재 챔피언 = 서빙이 읽는 LightGBM 아티팩트(`settings.crowd_lgbm_artifact`, env
    `CROWD_LGBM_ARTIFACT`). 설정이 None이면 `latest_artifact(kind="lightgbm")`."""
    from app.core.config import get_settings

    settings = get_settings()
    models_dir = Path(settings.crowd_models_dir)
    if settings.crowd_lgbm_artifact:
        return models_dir / settings.crowd_lgbm_artifact
    from app.CROWD.pipeline.predictor import latest_artifact

    found = latest_artifact(models_dir, kind="lightgbm")
    if found is None:
        raise FileNotFoundError("챔피언 LightGBM 아티팩트를 찾지 못했다")
    return found


def gate(ctx: Ctx) -> dict:
    try:
        champion = resolve_champion()
    except Exception as exc:  # 설정·아티팩트 문제 - 단계 실패로 기록
        return _record(ctx, "gate", 1, 0.0, {"error": f"챔피언 해석 실패: {exc}"})
    cmd = _py_cmd(
        ctx,
        "app.CROWD.pipeline.retrain.gate",
        "holdout",
        "--panel",
        str(processed_root() / ctx.wide_rel),
        "--events",
        str(processed_root() / ctx.events_rel),
        "--champion",
        str(champion),
        "--candidate",
        str(ctx.candidate_dir),
        "--split-date",
        ctx.split_date,
        "--out",
        str(ctx.candidate_dir / "gate.json"),
        "--register",
        str(candidates_path()),
        "--artifact-name",
        ctx.candidate_name,
    )
    result = _run_cmd(ctx, "gate", cmd)
    result["detail"]["champion"] = str(champion)
    ctx.gate_rc = result["rc"]
    return result


# ── 단계 8~10 ──
def _fmt(value, spec: str = "{:+.2f}") -> str:
    return "-" if value is None else spec.format(value)


def render_report(ctx: Ctx, gate_doc: dict | None) -> str:
    """`RETRAIN_REPORT.md` 본문."""
    verdict = {0: "채택(shadow 후보 등록)", 3: "기각"}.get(ctx.gate_rc, "미판정")
    lines = [
        f"# 재학습 리포트 - {ctx.candidate_name}",
        "",
        f"- 실행 ID: `{ctx.run_id}` · 기준일 D={ctx.today:%Y-%m-%d} · "
        f"학습 {TRAIN_START}~{ctx.end_date}",
        f"- holdout: split_date={ctx.split_date} 이후 {HOLDOUT_DAYS}일 · "
        f"피처셋 `{FEATURE_SET}`(mask stack)",
        f"- 게이트 판정: **{verdict}** (rc={ctx.gate_rc})",
        f"- 학습 피크 RSS: {_fmt(ctx.peak_rss_mb, '{:.0f} MB')}",
        f"- dry-run: {ctx.dry_run}",
        "",
        "## 단계",
        "",
        "| 단계 | rc | 소요(초) |",
        "| --- | --- | --- |",
    ]
    for s in ctx.rec["steps"]:
        lines.append(f"| {s['step']} | {s['rc']} | {s['sec']} |")
    lines += ["", "## 게이트 요약", ""]
    if gate_doc:
        lines.append(f"- accept: {gate_doc.get('accept')}")
        for reason in gate_doc.get("reasons") or []:
            lines.append(f"- 사유: {reason}")
        lines += [
            "",
            "| 타깃 | 챔피언 대비 점추정(%p) | CI 하한 | CI 상한 |",
            "| --- | --- | --- | --- |",
        ]
        for target, body in (gate_doc.get("targets") or {}).items():
            vs = body.get("vs_champion") or {}
            lines.append(
                f"| {target} | {_fmt(vs.get('point'))} | {_fmt(vs.get('ci_low'))} | "
                f"{_fmt(vs.get('ci_high'))} |"
            )
    else:
        lines.append("- gate.json 없음(게이트 미실행 또는 dry-run)")
    stamp = load_deploy_stamp()
    lines += ["", "## DEPLOY_STAMP", ""]
    lines.append(f"`{stamp}`" if stamp else "- DEPLOY_STAMP.json 없음")
    lines += [
        "",
        "## 승격 안내(사람이 한다 - 자동 승격 없음)",
        "",
        "1. shadow 예측(`scripts/run_crowd_shadow_predict.sh`)을 충분히 쌓아 shadow 모드 "
        "게이트를 본다.",
        "2. 채택하려면 `app.CROWD.pipeline.promote_artifact`로 후보를 `models/CROWD/`에 올린다.",
        f"3. `.env`의 `CROWD_LGBM_ARTIFACT=`를 `{ctx.candidate_name}`(승격한 폴더명)로 바꾸고 "
        "서비스를 재시작한다. 이전 값은 롤백용으로 적어 둔다.",
        "",
    ]
    return "\n".join(lines)


def report(ctx: Ctx) -> dict:
    start = time.monotonic()
    path = ctx.candidate_dir / "RETRAIN_REPORT.md"
    if ctx.dry_run:
        return _record(ctx, "report", 0, 0.0, {"dry_run": True, "path": str(path)})
    gate_doc = read_json(ctx.candidate_dir / "gate.json")
    atomic_write_text(path, render_report(ctx, gate_doc))
    return _record(ctx, "report", 0, time.monotonic() - start, {"path": str(path)})


def _send_discord(message: str) -> str:
    """Discord 전송. webhook env가 없으면 보내지 않고 stdout만. 결과 상태 문자열."""
    if not os.environ.get("DISCORD_WEBHOOK_URL"):
        return "skipped(no webhook)"
    try:
        from DATA_ENGINE.monitor.notify_discord import send_discord_notification

        return send_discord_notification(message).status
    except Exception as exc:  # 알림 실패가 재학습을 깨지 않게
        return f"failed({exc})"


def summary_line(ctx: Ctx, gate_doc: dict | None) -> str:
    verdict = "dry-run" if ctx.dry_run else {0: "채택", 3: "기각"}.get(ctx.gate_rc, "미판정")
    parts = []
    for target, body in ((gate_doc or {}).get("targets") or {}).items():
        vs = body.get("vs_champion") or {}
        parts.append(
            f"{target} {_fmt(vs.get('point'))}%p "
            f"[CI {_fmt(vs.get('ci_low'))}, {_fmt(vs.get('ci_high'))}]"
        )
    metrics = " · ".join(parts) if parts else "지표 없음"
    return f"[CROWD 재학습] {ctx.candidate_name} {verdict} - 챔피언 대비 {metrics}"


def notify(ctx: Ctx) -> dict:
    start = time.monotonic()
    gate_doc = None if ctx.dry_run else read_json(ctx.candidate_dir / "gate.json")
    line = summary_line(ctx, gate_doc)
    print(line, flush=True)
    if ctx.dry_run:
        return _record(ctx, "notify", 0, 0.0, {"dry_run": True, "message": line})
    status = _send_discord(line)
    return _record(ctx, "notify", 0, time.monotonic() - start, {"message": line, "discord": status})


def registered_names() -> set[str]:
    doc = read_json(candidates_path()) or {}
    return {c.get("artifact") for c in doc.get("candidates", []) if c.get("artifact")}


def apply_retention(keep: int, current_run: str) -> list[str]:
    """`processed/auto/`·`_experiments/auto/`에서 최신 `keep`개 run만 남긴다.

    shadow 후보로 등록된 run과 이번 run은 지우지 않는다. 지운 run ID 목록을 돌려준다.
    """
    runs: set[str] = set()
    proc = processed_root() / "auto"
    exp = experiments_root()
    if proc.is_dir():
        runs |= {p.name for p in proc.iterdir() if p.is_dir()}
    if exp.is_dir():
        runs |= {p.name.removeprefix("auto_") for p in exp.iterdir() if p.is_dir()}
    protected = {n.removeprefix("auto_") for n in registered_names()} | {current_run}
    removed = []
    for run_id in sorted(runs, reverse=True)[keep:]:
        if run_id in protected:
            continue
        shutil.rmtree(proc / run_id, ignore_errors=True)
        shutil.rmtree(exp / f"auto_{run_id}", ignore_errors=True)
        (interim_root() / "auto" / f"derived_{run_id}.parquet").unlink(missing_ok=True)
        removed.append(run_id)
    return removed


def mark_done(ctx: Ctx) -> dict:
    start = time.monotonic()
    if ctx.dry_run:
        return _record(
            ctx, "mark_done", 0, 0.0, {"dry_run": True, "had_request": ctx.request is not None}
        )
    detail: dict = {}
    if ctx.request is not None and REQUEST_PATH.exists():
        detail["request_done"] = str(drift.mark_done(REQUEST_PATH))
    ctx.state["last_candidate_date"] = f"{ctx.today:%Y-%m-%d}"
    detail["retention_removed"] = apply_retention(KEEP_RUNS, ctx.run_id)
    return _record(ctx, "mark_done", 0, time.monotonic() - start, detail)


# ── 실행 ──
def _finish(ctx: Ctx, status: str, code: int) -> int:
    ctx.rec.update(status=status, exit_code=code, finished_at=now_kst().isoformat())
    _save_state(ctx)
    return code


def _notify_failure(ctx: Ctx, step: str, rc: int) -> None:
    if not ctx.dry_run:
        _send_discord(f"[CROWD 재학습] {ctx.candidate_name} 실패 - 단계 {step} rc={rc}")


def run(ctx: Ctx) -> int:
    ctx.state.setdefault("runs", []).append(ctx.rec)
    del ctx.state["runs"][:-MAX_STATE_RUNS]
    _save_state(ctx)

    for name, fn in (("short_circuit", short_circuit), ("guard", guard)):
        rc = fn(ctx)["rc"]
        if rc == EXIT_SKIP:
            reason = ctx.rec["steps"][-1]["detail"].get("reason")
            print(f"[retrain] skip({name}): {reason}", flush=True)
            return _finish(ctx, "skipped", EXIT_SKIP)
        if rc != 0:
            print(f"[retrain] 실패({name}) rc={rc}", flush=True)
            return _finish(ctx, "failed", rc)

    for fn in (build_panel, to_wide, events, train, gate):
        res = fn(ctx)
        ok = res["rc"] in GATE_OK_CODES if res["step"] == "gate" else res["rc"] == 0
        if not ok:
            code = res["rc"] or 1
            print(f"[retrain] 실패({res['step']}) rc={code} - 이후 단계 중단", flush=True)
            _notify_failure(ctx, res["step"], code)
            return _finish(ctx, "failed", code)

    for fn in (report, notify, mark_done):
        res = fn(ctx)
        if res["rc"] != 0:
            return _finish(ctx, "failed", res["rc"])
    return _finish(ctx, "done", 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CROWD 재학습 러너(자동 승격 없음)")
    ap.add_argument("--force", action="store_true", help="요청·R3 없이도 진행")
    ap.add_argument("--skip-window", action="store_true", help="야간창 검사 생략")
    ap.add_argument("--full", action="store_true", help="Spark 재집계를 전 파티션으로")
    ap.add_argument("--dry-run", action="store_true", help="subprocess 실행 없이 명령만 기록")
    ap.add_argument("--run", default=None, help="실행 ID(기본: KST YYYYMMDD-HHMM)")
    ap.add_argument("--python", default=None, help="자식 프로세스용 파이썬(기본: 현재 인터프리터)")
    args = ap.parse_args(argv)

    now = now_kst()
    run_id = args.run or f"{now:%Y%m%d-%H%M}"
    ctx = Ctx(
        run_id=run_id,
        today=now.tz_localize(None).normalize(),
        now=now,
        python=args.python or sys.executable,
        force=args.force,
        skip_window=args.skip_window,
        full=args.full,
        dry_run=args.dry_run,
        state=read_json(STATE_PATH) or {},
    )
    ctx.rec = {
        "run": run_id,
        "started_at": now.isoformat(),
        "date": f"{ctx.today:%Y-%m-%d}",
        "force": args.force,
        "dry_run": args.dry_run,
        "full": args.full,
        "status": "running",
        "steps": [],
    }
    return run(ctx)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
