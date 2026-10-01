"""채점·드리프트 리포트 — 최근 채점 표와 드리프트 판정을 마크다운으로 렌더한다."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.CROWD.pipeline.retrain.common import (
    MONITORING_DIR,
    atomic_write_text,
    now_kst,
    read_json,
    today_kst,
    write_json,
)
from app.CROWD.pipeline.retrain.drift import load_score_metas


def _num(value, fmt: str = "{:.2f}") -> str:
    return "-" if value is None else fmt.format(value)


def render_score_table(metas: list[dict]) -> str:
    """채점 메타별 한 줄 — 날짜·가용성·예측기 버전·채점 행·결손 역·타깃별 RMSE와 개선율."""
    head = (
        "| 날짜 | 가용성 | 예측기 버전 | 채점 행 | 결손 역 | "
        "승차 RMSE(모델) | 승차 RMSE(lookup) | 승차 개선율(%) | "
        "하차 RMSE(모델) | 하차 RMSE(lookup) | 하차 개선율(%) |"
    )
    lines = [head, "|" + " --- |" * 11]
    for meta in metas:
        cells = [
            str(meta.get("target_date", "-")),
            str(meta.get("availability", "-")),
            str(meta.get("predictor_version", "-")),
            str(meta.get("rows_scored", "-")),
            str(meta.get("missing_station_count", "-")),
        ]
        for target in ("boarding", "alighting"):
            m = (meta.get("metrics") or {}).get(target) or {}
            cells += [
                _num(m.get("rmse_model")),
                _num(m.get("rmse_lookup")),
                _num(m.get("improvement_rmse_pct"), "{:+.2f}"),
            ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_drift_section(drift: dict) -> str:
    r0, r1, r3 = drift.get("r0", {}), drift.get("r1", {}), drift.get("r3", {})
    out = [
        f"- 기준일: {drift.get('date', '-')}",
        (
            f"- R0 데이터 보류: {'보류' if r0.get('hold') else '정상'} "
            f"(최근 창 결손 {r0.get('missing_days', '-')}일)"
        ),
    ]
    alerts = r1.get("alerts", [])
    if r1.get("skipped_reason"):
        out.append(f"- R1' 성능 경보: 건너뜀 ({r1['skipped_reason']})")
    else:
        out.append(
            f"- R1' 성능 경보: {len(alerts)}건 (표본 부족으로 건너뜀 {len(r1.get('skipped', []))}건)"
        )
    for a in alerts:
        out.append(
            f"  - {a['availability']} / {a['target']}: 개선율 {a['point']:+.2f}% "
            f"[{a['ci_low']:+.2f}, {a['ci_high']:+.2f}] — {a['reason']}"
        )
    out.append(
        f"- R3 달력 트리거: {'due' if r3.get('due') else 'not due'} ({r3.get('reason', '-')})"
    )
    req = drift.get("request") or {}
    out.append(f"- 재학습 요청 파일: {req.get('status', '-')}")
    return "\n".join(out)


def render_score_report(metas: list[dict], drift: dict | None, generated_at: str | datetime) -> str:
    stamp = generated_at.isoformat() if isinstance(generated_at, datetime) else str(generated_at)
    parts = [
        "# 혼잡도 예측 채점 리포트",
        "",
        f"생성 시각: {stamp}",
        "",
        "## 최근 채점",
        "",
        render_score_table(metas) if metas else "채점 결과가 없다.",
        "",
        "## 드리프트 판정",
        "",
        render_drift_section(drift) if drift else "드리프트 판정 결과가 없다.",
        "",
        "## 주의",
        "",
        "- 등급 일치율은 L2 의사정답이라 이 리포트에 포함하지 않는다.",
        "- 결손 역은 채우지 않고 공통 행만 채점한다(원칙 8).",
        "",
    ]
    return "\n".join(parts)


def write_gate_json(path: Path, gate: dict) -> None:
    """게이트 판정 JSON을 원자적으로 쓴다. 스키마는 P4에서 정해지므로 지금은 얇은 래퍼다."""
    write_json(path, gate)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="채점 리포트(마크다운) 생성")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--score-dir", default=None)
    ap.add_argument("--monitoring-dir", default=str(MONITORING_DIR))
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    monitoring = Path(args.monitoring_dir)
    score_dir = Path(args.score_dir) if args.score_dir else monitoring / "score_daily"
    out = Path(args.out) if args.out else monitoring / "SCORE_REPORT.md"
    today = today_kst()
    metas = load_score_metas(score_dir, today - pd.Timedelta(days=args.days), today)
    drift = read_json(monitoring / "drift_latest.json")
    atomic_write_text(out, render_score_report(metas, drift, now_kst()))
    print(f"[리포트] {out} (채점 {len(metas)}일)", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
