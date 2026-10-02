"""운영 지표 조회 — 파일 시스템의 채점·게이트·러너 상태·Spark meta를 읽기만 한다.

json·pathlib·datetime만 쓴다(pandas·pyarrow·pyspark 금지). parquet은 열지 않고 사이드카 json만
읽는다. 디렉터리가 없으면 빈 배열이고, 깨진 파일은 그 파일만 건너뛰며 warning을 남긴다.
응답은 엔드포인트·파라미터별로 60초 캐시한다(`clear_cache`로 비운다).
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.ops")

AI_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))
CACHE_TTL_SEC = 60.0
# retrain/common.py의 SCORE_META_NAME과 같다(import하면 pandas·numpy가 딸려 온다).
SCORE_META_NAME = "part.meta.json"
_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


class InvalidSourceError(ValueError):
    """`source` 파라미터 형식 오류."""


@dataclass(frozen=True)
class OpsPaths:
    monitoring_dir: Path  # score_daily/·score_shadow/·retrain_state.json·shadow_candidates.json
    experiments_dir: Path  # <auto_<run>>/gate.json
    processed_auto_dir: Path  # crowd_panel_rebuild의 meta.json
    spark_exp_dir: Path  # replay_kafka 등 spark_exp 실험의 meta.json


def default_paths() -> OpsPaths:
    return OpsPaths(
        monitoring_dir=AI_ROOT / "data" / "CROWD" / "monitoring",
        experiments_dir=AI_ROOT / "models" / "CROWD" / "_experiments" / "auto",
        processed_auto_dir=AI_ROOT / "data" / "CROWD" / "processed" / "auto",
        spark_exp_dir=AI_ROOT / "data" / "CROWD" / "interim" / "spark_exp",
    )


_paths: OpsPaths | None = None
_cache: dict[tuple, tuple[float, list]] = {}


def get_paths() -> OpsPaths:
    global _paths
    if _paths is None:
        _paths = default_paths()
    return _paths


def set_paths_for_test(paths: OpsPaths | None) -> None:
    """경로를 바꿔 끼운다(None이면 기본값으로 복귀). 캐시도 함께 비운다."""
    global _paths
    _paths = paths
    clear_cache()


def clear_cache() -> None:
    _cache.clear()


def _cached(key: tuple, build: Callable[[], list]) -> list:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    rows = build()
    _cache[key] = (now, rows)
    return rows


# ── 공통 ──
def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(number)


def _str(value: Any) -> str | None:
    return None if value is None else str(value)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("ops: %s 읽기 실패 — 건너뜀 (%s)", path, exc)
        return None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=KST)


def _ts_key(value: Any) -> datetime:
    return _parse_ts(value) or _EPOCH


# ── score-daily ──
def _score_root(source: str) -> Path:
    mon = get_paths().monitoring_dir
    if source == "champion":
        return mon / "score_daily"
    if source.startswith("shadow:"):
        name = source.split(":", 1)[1]
        if not _NAME_RE.fullmatch(name) or name in (".", ".."):
            raise InvalidSourceError(f"shadow 후보 이름이 올바르지 않다: {name!r}")
        return mon / "score_shadow" / name
    raise InvalidSourceError("source는 champion 또는 shadow:<artifact> 여야 한다")


def _score_metas(source: str, days: int) -> list[tuple[str, dict]]:
    root = _score_root(source)
    if not root.is_dir():
        return []
    dirs = sorted(p for p in root.glob("dt=*") if p.is_dir())[-days:]
    out = []
    for d in dirs:
        meta_path = d / SCORE_META_NAME
        if not meta_path.is_file():
            continue
        meta = _read_json(meta_path)
        if isinstance(meta, dict):
            out.append((d.name.removeprefix("dt="), meta))
    return out


def _metric(block: Any, target: str, key: str) -> float | None:
    sub = block.get(target) if isinstance(block, dict) else None
    return _num(sub.get(key)) if isinstance(sub, dict) else None


def score_daily(days: int, source: str) -> list[dict]:
    def build() -> list[dict]:
        rows = []
        for day, meta in _score_metas(source, days):
            m = meta.get("metrics")
            rows.append(
                {
                    "date": day,
                    "source": source,
                    "availability": _str(meta.get("availability")),
                    "predictor_version": _str(meta.get("predictor_version")),
                    "rows_scored": _int(meta.get("rows_scored")),
                    "missing_station_count": _int(meta.get("missing_station_count")),
                    "boarding_rmse_model": _metric(m, "boarding", "rmse_model"),
                    "boarding_rmse_lookup": _metric(m, "boarding", "rmse_lookup"),
                    "boarding_improvement_rmse_pct": _metric(m, "boarding", "improvement_rmse_pct"),
                    "boarding_mae_model": _metric(m, "boarding", "mae_model"),
                    "alighting_rmse_model": _metric(m, "alighting", "rmse_model"),
                    "alighting_rmse_lookup": _metric(m, "alighting", "rmse_lookup"),
                    "alighting_improvement_rmse_pct": _metric(
                        m, "alighting", "improvement_rmse_pct"
                    ),
                    "alighting_mae_model": _metric(m, "alighting", "mae_model"),
                }
            )
        return rows

    _score_root(source)  # 잘못된 source는 캐시에 닿기 전에 거른다
    return _cached(("score_daily", days, source), build)


def score_by_line(days: int) -> list[dict]:
    def build() -> list[dict]:
        rows = []
        for day, meta in _score_metas("champion", days):
            by_line = meta.get("by_line")
            if not isinstance(by_line, dict):
                continue
            for line in sorted(by_line):
                blk = by_line[line]
                if not isinstance(blk, dict):
                    continue
                rows.append(
                    {
                        "date": day,
                        "line": str(line),
                        "n": _int(blk.get("n")),
                        "boarding_rmse_model": _metric(blk, "boarding", "rmse_model"),
                        "boarding_improvement_rmse_pct": _metric(
                            blk, "boarding", "improvement_rmse_pct"
                        ),
                        "alighting_rmse_model": _metric(blk, "alighting", "rmse_model"),
                        "alighting_improvement_rmse_pct": _metric(
                            blk, "alighting", "improvement_rmse_pct"
                        ),
                    }
                )
        return rows

    return _cached(("score_by_line", days), build)


# ── gate ──
def _gate_stat(targets: dict, target: str, key: str) -> float | None:
    blk = targets.get(target)
    vs = blk.get("vs_champion") if isinstance(blk, dict) else None
    return _num(vs.get(key)) if isinstance(vs, dict) else None


def gate(limit: int) -> list[dict]:
    def build() -> list[dict]:
        paths = get_paths()
        cands = _read_json(paths.monitoring_dir / "shadow_candidates.json")
        registered: set[str] = set()
        if isinstance(cands, dict):
            registered = {
                str(c.get("artifact"))
                for c in cands.get("candidates", [])
                if isinstance(c, dict) and c.get("artifact")
            }
        rows = []
        root = paths.experiments_dir
        for gate_path in sorted(root.glob("*/gate.json")) if root.is_dir() else []:
            doc = _read_json(gate_path)
            if not isinstance(doc, dict):
                continue
            dirname = gate_path.parent.name  # 후보 아티팩트 이름(auto_<run>)
            window = doc.get("window") if isinstance(doc.get("window"), list) else []
            targets = doc.get("targets") if isinstance(doc.get("targets"), dict) else {}
            rows.append(
                {
                    "run": dirname.removeprefix("auto_"),
                    "mode": _str(doc.get("mode")),
                    "window_start": _str(window[0]) if len(window) > 0 else None,
                    "window_end": _str(window[1]) if len(window) > 1 else None,
                    "decided_at": _str(doc.get("decided_at")),
                    "accepted": bool(doc.get("accept")),
                    "boarding_point_pp": _gate_stat(targets, "boarding", "point"),
                    "boarding_ci_low_pp": _gate_stat(targets, "boarding", "ci_low"),
                    "alighting_point_pp": _gate_stat(targets, "alighting", "point"),
                    "alighting_ci_low_pp": _gate_stat(targets, "alighting", "ci_low"),
                    "registered_shadow": dirname in registered,
                }
            )
        rows.sort(key=lambda r: _ts_key(r["decided_at"]), reverse=True)
        return rows[:limit]

    return _cached(("gate", limit), build)


# ── jobs ──
def jobs(limit: int) -> list[dict]:
    def build() -> list[dict]:
        state = _read_json(get_paths().monitoring_dir / "retrain_state.json")
        runs = state.get("runs") if isinstance(state, dict) else None
        if not isinstance(runs, list):
            return []
        recs = [r for r in runs if isinstance(r, dict)]
        recs.sort(key=lambda r: _ts_key(r.get("started_at")), reverse=True)
        rows = []
        for rec in recs[:limit]:
            base = {
                "run_id": str(rec.get("run", "")),
                "status": _str(rec.get("status")),
                "started_at": _str(rec.get("started_at")),
                "finished_at": _str(rec.get("finished_at")),
                "exit_code": _int(rec.get("exit_code")),
            }
            steps = [s for s in rec.get("steps", []) if isinstance(s, dict)]
            if not steps:
                rows.append({**base, "step": None, "step_rc": None, "step_sec": None})
            for s in steps:
                rows.append(
                    {
                        **base,
                        "step": _str(s.get("step")),
                        "step_rc": _int(s.get("rc")),
                        "step_sec": _num(s.get("sec")),
                    }
                )
        return rows

    return _cached(("jobs", limit), build)


# ── spark-runs ──
def _spark_row(path: Path, root: Path, meta: dict, is_panel_root: bool) -> dict:
    parent = path.parent.name
    if is_panel_root:
        job = "panel_rebuild"
    elif parent.startswith("replay_"):
        job = "replay_kafka"
    else:
        job = "unknown"
    run = meta.get("run") or parent.removeprefix("replay_")
    generated = meta.get("generated_at")
    if not generated:  # replay meta에는 generated_at이 없어 파일 수정 시각으로 대신한다
        try:
            mtime = path.stat().st_mtime
            generated = datetime.fromtimestamp(mtime, KST).isoformat(timespec="seconds")
        except OSError:
            generated = None
    rows = meta.get("panel_rows") if "panel_rows" in meta else meta.get("events_written")
    verify = meta.get("verify") if isinstance(meta.get("verify"), dict) else {}
    passed = verify.get("passed")
    compare_path = path.parent / "compare.json"
    if passed is None and job == "replay_kafka" and compare_path.is_file():
        cmp_doc = _read_json(compare_path)  # replay의 검증 결과는 compare.json의 match다
        passed = cmp_doc.get("match") if isinstance(cmp_doc, dict) else None
    spark = meta.get("spark") if isinstance(meta.get("spark"), dict) else {}
    try:
        rel = path.relative_to(root.parent).as_posix()
    except ValueError:
        rel = path.name
    return {
        "job": job,
        "run": str(run),
        "generated_at": _str(generated),
        "elapsed_sec": _num(meta.get("elapsed_sec")),
        "peak_rss_mb": _num(meta.get("peak_rss_mb")),
        "rows": _int(rows),
        "input_partitions": _int(meta.get("input_partitions")),
        "verify_passed": passed if isinstance(passed, bool) else None,
        "verify_max_abs_err": _num(verify.get("max_abs_err")),
        "cores": _str(spark.get("cores")),
        "driver_memory": _str(spark.get("driver_memory")),
        "path": rel,
    }


def spark_runs(limit: int) -> list[dict]:
    def build() -> list[dict]:
        paths = get_paths()
        rows = []
        for root, is_panel in ((paths.processed_auto_dir, True), (paths.spark_exp_dir, False)):
            if not root.is_dir():
                continue
            for meta_path in sorted(root.glob("**/meta.json")):
                meta = _read_json(meta_path)
                if isinstance(meta, dict):
                    rows.append(_spark_row(meta_path, root, meta, is_panel))
        rows.sort(key=lambda r: _ts_key(r["generated_at"]), reverse=True)
        return rows[:limit]

    return _cached(("spark_runs", limit), build)
