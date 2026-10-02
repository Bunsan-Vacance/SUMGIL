"""로컬 Grafana 검증용 합성 데이터 생성기 (S15P21A104-341 W1-4).

ops API(`app/ops/service.py`)가 읽는 사이드카 json과 node-exporter textfile(`.prom`)을 만든다.
표준 라이브러리만 쓴다(textfile 본문은 `DATA_ENGINE.observability.export_textfile.render` 재사용).

**전부 합성 데이터다.** json은 `"synthetic": true` 키, textfile은 첫 줄 주석과 `.synthetic` 마커로
표시한다. 실제 운영 수치가 아니므로 해석·보고에 쓰지 않는다.

    python validation/INFRA/observability-check/fixtures/make_fixtures.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
AI_ROOT = HERE.parents[3]  # AI/validation/INFRA/observability-check/fixtures -> AI
KST = timezone(timedelta(hours=9))
DAYS = 30
SHADOW_DAYS = 14
MISSING_DAY_OFFSET = 9  # 오늘로부터 며칠 전 하루를 결측(NaN -> null)으로 둔다
SHADOW_NAME = "auto_synth-r2"  # README에서 $shadow 변수에 넣을 값


def write_json(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iso(day: date, hour: int = 9) -> str:
    return datetime(day.year, day.month, day.day, hour, tzinfo=KST).isoformat(timespec="seconds")


def target(rmse: float | None, lookup: float | None) -> dict:
    if rmse is None or lookup is None:
        return {
            "n": 0,
            "rmse_model": None,
            "rmse_lookup": None,
            "mae_model": None,
            "mae_lookup": None,
            "improvement_rmse_pct": None,
            "improvement_mae_pct": None,
        }
    imp = round((lookup - rmse) / lookup * 100, 2)
    return {
        "n": 5000,
        "rmse_model": round(rmse, 3),
        "rmse_lookup": round(lookup, 3),
        "mae_model": round(rmse * 0.55, 3),
        "mae_lookup": round(lookup * 0.55, 3),
        "improvement_rmse_pct": imp,
        "improvement_mae_pct": imp,
    }


def score_meta(day: date, idx: int, total: int, *, missing: bool, shift: float = 0.0) -> dict:
    """idx=0이 가장 오래된 날. 추세: 모델 RMSE가 서서히 나빠지고(드리프트) 요일 주기를 섞는다."""
    wave = math.sin(idx / 7 * 2 * math.pi)
    drift = idx / total * 1.6
    b_model = 38 + drift + wave * 1.5 + shift
    a_model = 35 + drift * 0.8 + wave * 1.3 + shift
    b_look = 45 + wave * 1.2
    a_look = 41 + wave * 1.0
    if missing:
        b = a = target(None, None)
    else:
        b, a = target(b_model, b_look), target(a_model, a_look)
    availability = "no_lag" if idx % 11 == 5 else ("d1_only" if idx % 5 == 2 else "full")
    by_line = {
        line: {
            "n": 0 if missing else 600,
            "boarding": b if missing else target(b_model * f, b_look),
            "alighting": a if missing else target(a_model * f, a_look),
        }
        for line, f in (("1호선", 1.12), ("2호선", 0.95), ("3호선", 1.0))
    }
    return {
        "synthetic": True,
        "target_date": day.isoformat(),
        "availability": availability,
        "predictor_version": "synthetic_gru_v3",
        "rows_scored": 0 if missing else 5000 + idx * 7,
        "missing_station_count": 2 + idx % 3 if idx % 6 == 0 else 0,
        "metrics": {"boarding": b, "alighting": a},
        "by_line": by_line,
    }


def make_monitoring(root: Path, today: date) -> list[Path]:
    mon = root / "monitoring"
    written: list[Path] = []
    for i in range(DAYS):
        day = today - timedelta(days=DAYS - i)
        missing = (DAYS - i) == MISSING_DAY_OFFSET
        p = mon / "score_daily" / f"dt={day}" / "part.meta.json"
        write_json(p, score_meta(day, i, DAYS, missing=missing))
        written.append(p)
    for i in range(SHADOW_DAYS):
        day = today - timedelta(days=SHADOW_DAYS - i)
        p = mon / "score_shadow" / SHADOW_NAME / f"dt={day}" / "part.meta.json"
        write_json(p, score_meta(day, i, DAYS, missing=False, shift=-2.0))
        written.append(p)

    write_json(
        mon / "shadow_candidates.json",
        {
            "synthetic": True,
            "candidates": [
                {"artifact": SHADOW_NAME, "registered_at": iso(today - timedelta(days=SHADOW_DAYS))}
            ],
        },
    )

    def step(name: str, rc: int, sec: float) -> dict:
        return {"step": name, "rc": rc, "sec": sec, "detail": {}}

    runs = [
        {
            "run": "synth-r1",
            "started_at": iso(today - timedelta(days=21), 8),
            "finished_at": iso(today - timedelta(days=21), 9),
            "status": "ok",
            "exit_code": 0,
            "steps": [step("panel", 0, 312.4), step("gate", 0, 88.1), step("shadow", 0, 41.0)],
        },
        {
            "run": "synth-r2",
            "started_at": iso(today - timedelta(days=14), 8),
            "finished_at": iso(today - timedelta(days=14), 9),
            "status": "ok",
            "exit_code": 0,
            "steps": [step("panel", 0, 305.9), step("gate", 0, 91.7), step("shadow", 0, 39.2)],
        },
        {
            "run": "synth-r3",
            "started_at": iso(today - timedelta(days=7), 8),
            "status": "failed",
            "exit_code": 1,
            "steps": [step("panel", 0, 322.0), step("gate", 1, 12.5)],
        },
    ]
    write_json(mon / "retrain_state.json", {"synthetic": True, "runs": runs})
    written += [mon / "shadow_candidates.json", mon / "retrain_state.json"]
    return written


# ── 데이터 품질 사이드카 (보드 ⑥, S15P21A104-341 D5) ──
DQ_DAYS = 30
FEATURE_DAYS = 8
DQ_EXPECTED_STATIONS = 625
DQ_LINES = ("1호선", "2호선", "3호선", "4호선", "5호선", "6호선", "7호선")
DQ_OUTLIER_OFFSET = 4  # 오늘로부터 며칠 전: 이상치 17건·DQ4
DQ_MISSING_OFFSET = 12  # 결손 역 3개·DQ1
DQ_SCHEMA_OFFSET = 7  # schema_ok false·DQ6
DQ_ADJUSTED_OFFSETS = (1, 2)  # z_adjusted를 싣는 날(--level-adjust 흉내)
FEATURE_NAMES = (
    "game_count",
    "festival_count",
    "festival_short_count",
    "festival_long_count",
    "festival_min_duration_days",
    "lag1d_boarding_resid",
    "lag1d_alighting_resid",
    "lagsd_boarding_resid",
    "lagsd_alighting_resid",
    "lag7d_boarding_resid",
    "lag7d_alighting_resid",
    "temp_c",
)
FEATURE_CRIT_OFFSET = 3  # PSI crit 2개(TD1:*)인 날
OUTLIER_STATIONS = (
    (222, "강남", "2호선"),
    (239, "잠실", "2호선"),
    (150, "서울역", "1호선"),
    (426, "고속터미널", "3호선"),
    (320, "사당", "4호선"),
    (544, "여의도", "5호선"),
    (633, "공덕", "6호선"),
    (727, "강남구청", "7호선"),
)


def _dq_line_totals(idx: int, offset: int) -> list[dict]:
    """호선 총량 z에 추세를 준다: 2호선은 서서히 음(-)으로, 5호선은 양(+)으로 밀린다."""
    items = []
    for k, line in enumerate(DQ_LINES):
        mean = 1_500_000 - k * 140_000
        std = mean * 0.03
        z = math.sin((idx + k * 2) / 5) * 0.9
        if line == "2호선":
            z -= idx / DQ_DAYS * 3.4
        if line == "5호선":
            z += idx / DQ_DAYS * 2.6
        item = {
            "line": line,
            "total": round(mean + z * std),
            "baseline_mean": mean,
            "baseline_std": round(std),
            "z": round(z, 2),
        }
        if offset in DQ_ADJUSTED_OFFSETS:
            item["z_adjusted"] = round(z * 0.45, 2)
        items.append(item)
    return items


def _dq_outliers(n: int) -> list[dict]:
    out = []
    for i in range(n):
        no, name, line = OUTLIER_STATIONS[i % len(OUTLIER_STATIONS)]
        mean = 18_000 - i * 700
        std = 1_200
        z = (5.8 - i * 0.16) * (1 if i % 4 else -1)
        out.append(
            {
                "station_no": no + (i // len(OUTLIER_STATIONS)),
                "station_name": name,
                "line": line,
                "time_slot": f"{7 + i % 4:02d}-{8 + i % 4:02d}",
                "direction": "boarding" if i % 2 == 0 else "alighting",
                "value": round(mean + z * std),
                "baseline_mean": mean,
                "baseline_std": std,
                "z": round(z, 2),
            }
        )
    return out


def _quantiles(scale: float) -> dict:
    """`input_drift.quantiles()`의 실제 키는 "5","25",...이다. ops service는 `q5` 키를 읽으므로 둘 다 싣는다."""
    vals = {
        "5": 0.0,
        "25": 40.0 * scale,
        "50": 110.0 * scale,
        "75": 260.0 * scale,
        "95": 640.0 * scale,
    }
    return {**vals, **{f"q{k}": v for k, v in vals.items()}}


def _dq_day_doc(i: int, day: date, offset: int) -> dict:
    weekend = day.weekday() >= 5
    missing = [1234, 2345, 3456] if offset == DQ_MISSING_OFFSET else []
    alerts = ["DQ1"] if missing else []
    outlier_n = 17 if offset == DQ_OUTLIER_OFFSET else (i * 3) % 5
    if offset == DQ_OUTLIER_OFFSET:
        alerts.append("DQ4")
    schema_ok = offset != DQ_SCHEMA_OFFSET
    if not schema_ok:
        alerts.append("DQ6")
    day_type = "일요일" if day.weekday() == 6 else ("토요일" if weekend else "평일")
    return {
        "date": day.isoformat(),
        "baseline_version": "synthetic@3987000",
        "day_type": day_type,
        "rows": (7_600 if weekend else 10_900) - len(missing) * 20 + (i * 13) % 90,
        "stations": DQ_EXPECTED_STATIONS - len(missing),
        "expected_stations": DQ_EXPECTED_STATIONS,
        "missing_stations": missing,
        "nan_ratio": 0.002 if i % 9 == 0 else 0.0,
        "zero_ratio": round(0.028 + 0.004 * math.sin(i / 3), 4),
        "zero_ratio_baseline": 0.028,
        "line_totals": _dq_line_totals(i, offset),
        "slot_js": round(0.012 + 0.006 * abs(math.sin(i / 4)) + (0.05 if offset == 10 else 0), 4),
        "schema_ok": schema_ok,
        "collect_lag_days": 4 if offset == 15 else 1,
        "outlier_count": outlier_n,
        "outliers_top": _dq_outliers(min(outlier_n, 50)),
        "alerts": alerts,
        "generated_at": iso(day + timedelta(days=1), 10),
        "synthetic": True,
    }


def _feature_day_doc(i: int, day: date, offset: int) -> dict:
    crit_day = offset == FEATURE_CRIT_OFFSET
    feats = []
    for k, name in enumerate(FEATURE_NAMES):
        psi = round(0.02 + 0.012 * k + 0.004 * math.sin(i + k), 4)
        if k == 3:
            psi = round(0.12 + 0.01 * i, 4)  # 노랑대
        if crit_day and name.startswith("lag1d_"):
            psi = round(0.31 + 0.02 * k, 4)  # TD1 crit 2개
        level = "crit" if psi >= 0.25 else ("warn" if psi >= 0.1 else "ok")
        feats.append(
            {
                "name": name,
                "psi": psi,
                "ks": round(psi * 0.9, 4),
                "ks_p": 0.0004 if level == "crit" else round(0.2 + 0.05 * k, 4),
                "level": level,
                "n_train": 3_987_000,
                "n_recent": 280_000,
            }
        )
    no_lag = round(0.04 + 0.01 * i, 4)
    recent = {"full": round(0.77 - no_lag, 4), "d1_only": 0.18, "d7_only": 0.05, "no_lag": no_lag}
    return {
        "date": day.isoformat(),
        "window": [(day - timedelta(days=27)).isoformat(), day.isoformat()],
        "window_days": 28,
        "feature_set": "synthetic_feature_set",
        "features": feats,
        "targets": {
            "boarding": {
                "baseline": _quantiles(1.0),
                "recent": _quantiles(1.0 + 0.012 * i),
                "shifted": False,
            },
            "alighting": {
                "baseline": _quantiles(0.95),
                "recent": _quantiles(0.95 + 0.01 * i),
                "shifted": False,
            },
        },
        # input_drift는 {"baseline": {...}, "recent": {...}} 중첩으로 쓴다. ops service는 최상위 키를
        # 읽으므로 recent 값을 최상위에도 싣는다(키 불일치 확인 전까지 보드가 비지 않게).
        "availability_ratio": {
            "baseline": {"full": 0.7, "d1_only": 0.2, "d7_only": 0.05, "no_lag": 0.05},
            "recent": recent,
            **recent,
        },
        "alerts": [f"TD1:{f['name']}" for f in feats if f["level"] == "crit"],
        "generated_at": iso(day + timedelta(days=1), 10),
        "synthetic": True,
    }


def make_data_quality(root: Path, today: date) -> list[Path]:
    """`monitoring/data_quality/dt=*/part.json`(설계 3절)과 `features/dt=*/part.json`을 쓴다."""
    base = root / "monitoring" / "data_quality"
    written: list[Path] = []
    for i in range(DQ_DAYS):
        offset = DQ_DAYS - i
        day = today - timedelta(days=offset)
        p = base / f"dt={day}" / "part.json"
        write_json(p, _dq_day_doc(i, day, offset))
        written.append(p)
    for i in range(FEATURE_DAYS):
        offset = FEATURE_DAYS - i
        day = today - timedelta(days=offset)
        p = base / "features" / f"dt={day}" / "part.json"
        write_json(p, _feature_day_doc(i, day, offset))
        written.append(p)
    return written


def make_gates(models_root: Path, today: date) -> list[Path]:
    def gate(accept: bool, decided: date, point: float, reasons: list[str]) -> dict:
        vs = {"point": point, "ci_low": round(point - 1.4, 2), "ci_high": round(point + 1.4, 2)}
        return {
            "synthetic": True,
            "accept": accept,
            "reasons": reasons,
            "mode": "shadow",
            "window": [(decided - timedelta(days=28)).isoformat(), decided.isoformat()],
            "targets": {"boarding": {"vs_champion": vs}, "alighting": {"vs_champion": vs}},
            "decided_at": iso(decided),
        }

    docs = {
        "auto_synth-r2": gate(True, today - timedelta(days=14), 3.8, []),
        "auto_synth-r3": gate(False, today - timedelta(days=7), 0.6, ["ci_low <= 0"]),
    }
    out = []
    for name, doc in docs.items():
        p = models_root / name / "gate.json"
        write_json(p, doc)
        out.append(p)
    return out


def make_spark(root: Path, today: date) -> list[Path]:
    out = []
    # (rows, elapsed_sec, peak_rss_mb, verify_ok) — 행이 늘면 시간·메모리도 늘고 한 번은 검증 실패
    panel_runs = [
        (4_200_000, 61.0, 1450.0, True),
        (6_800_000, 94.5, 1720.0, True),
        (9_000_000, 128.3, 2050.0, True),
        (11_500_000, 171.9, 2390.0, True),
        (14_000_000, 214.0, 2810.0, False),
        (16_200_000, 252.4, 3120.0, True),
    ]
    for i, (rows, sec, rss, ok) in enumerate(panel_runs):
        latest = i == len(panel_runs) - 1
        name = "meta.json" if latest else f"synth_hist_{i}/meta.json"
        path = root / "processed" / "auto" / name
        gen = today - timedelta(days=(len(panel_runs) - 1 - i) * 5)
        write_json(
            path,
            {
                "synthetic": True,
                "run": f"synth-p{i + 1}",
                "input_partitions": 270,
                "new_rows": rows // 270,
                "panel_rows": rows,
                "duplicate_keys": {"new": 0, "final": 0},
                "verify": {"passed": ok, "max_abs_err": 0.0 if ok else 0.37, "rows_match": ok},
                "elapsed_sec": sec,
                "peak_rss_mb": rss,
                "spark": {"cores": "2", "driver_memory": "2g"},
                "generated_at": iso(gen, 10),
            },
        )
        out.append(path)

    replays = [(120_000, 14.2), (480_000, 41.8), (910_000, 77.5)]
    for i, (events, sec) in enumerate(replays):
        d = root / "interim" / "spark_exp" / f"replay_synth-{i + 1}"
        write_json(
            d / "meta.json",
            {
                "synthetic": True,
                "topic": "synthetic-topic",
                "events_written": events,
                "elapsed_sec": sec,
                "spark": {"cores": "2", "driver_memory": "1g"},
            },
        )
        write_json(d / "compare.json", {"synthetic": True, "match": i != 1})
        out += [d / "meta.json", d / "compare.json"]
    return out


def make_textfiles(textfile_dir: Path) -> list[Path]:
    sys.path.insert(0, str(AI_ROOT))
    from DATA_ENGINE.observability.export_textfile import render  # noqa: PLC0415

    now = int(time.time())
    hour = 3600
    cases = [
        # job, rc, duration, steps, ok_rcs, previous_success
        ("crowd_score_daily", 0, 412.6, [("archive", 0), ("score", 0)], {0, 99}, None),
        ("crowd_retrain", 99, 655.0, [("panel", 0), ("gate", 99)], {0, 99}, None),
        # 실패 + 마지막 성공은 40시간 전 -> 임계(24h 노랑, 36h 빨강)를 넘겨 빨강으로 보인다
        ("crowd_collect", 1, 18.2, [("fetch", 1)], {0}, now - 40 * hour),
    ]
    out = []
    textfile_dir.mkdir(parents=True, exist_ok=True)
    for job, rc, dur, steps, ok, prev in cases:
        body = render(job, rc, dur, steps, ok, {}, now, prev)
        text = "# SYNTHETIC: 로컬 검증용 합성 데이터 (make_fixtures.py) - 운영 수치 아님\n" + body
        path = textfile_dir / f"sumgil_{job}.prom"
        path.write_text(text, encoding="utf-8", newline="\n")
        marker = textfile_dir / f"sumgil_{job}.prom.synthetic"
        marker.write_text("synthetic\n", encoding="utf-8", newline="\n")
        out += [path, marker]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--root", type=Path, default=AI_ROOT / "data" / "CROWD")
    ap.add_argument(
        "--models-root",
        type=Path,
        default=AI_ROOT / "models" / "CROWD" / "_experiments" / "auto",
    )
    ap.add_argument(
        "--skip-data-quality",
        action="store_true",
        help="monitoring/data_quality 합성 생성을 건너뛴다(실데이터 사이드카가 이미 있을 때)",
    )
    ap.add_argument("--textfile-dir", type=Path, default=HERE.parent / "textfile")
    args = ap.parse_args()

    today = date.today()
    files = make_monitoring(args.root, today)
    if args.skip_data_quality:
        print("데이터 품질 합성 생성 건너뜀(--skip-data-quality)")
    else:
        files += make_data_quality(args.root, today)
    files += make_gates(args.models_root, today)
    files += make_spark(args.root, today)
    files += make_textfiles(args.textfile_dir)
    print(f"합성 파일 {len(files)}개 생성 (오늘 기준 {today})")
    for base in (args.root, args.models_root, args.textfile_dir):
        print(f"  - {os.path.abspath(base)}")
    print(f"shadow 패널 변수 $shadow 에는 {SHADOW_NAME} 를 입력한다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
