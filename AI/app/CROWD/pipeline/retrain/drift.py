"""드리프트 판정 — R0·R1'·R3 규칙으로 재학습 요청 파일을 만든다.

## 규칙

- **R0 데이터 보류.** 최근 `window_days`(28)일 중 채점 결과가 없는 날이 `max_missing`(7)일을
  넘으면 hold — 실측이 모자란 상태에서 성능 판정을 하지 않는다(원칙 8: 표본 부족 구간에 값을
  채우지 않는다). hold면 R1'은 건너뛴다.
- **R1' 성능 경보.** 가용성(`availability`)별·타깃별로 모델 대 lookup 개선율을 날짜 블록
  부트스트랩으로 재서 CI 상한이 0 미만(= 모델이 lookup보다 확실히 나쁨)이면 경보. 기준값
  (`baseline`)이 있으면 점추정이 기준 − `drop_pp`%p 아래로 떨어진 경우도 경보. 날짜가 7개 미만인
  그룹은 건너뛴다.
- **R3 달력 트리거.** 매달 첫 일요일이고 마지막 후보 이후 채점일이 20일 이상 쌓였으면 due.
- R2(대시보드 전용 규칙)는 구현하지 않는다.

## 요청 파일

R3가 due이고 유효한 요청이 없으면 `retrain_request.json`을 쓴다. TTL(기본 7일)이 지나면
`retrain_request.expired.json`으로 이름을 바꾸고(덮어씀), 처리가 끝나면 `mark_done`이
`retrain_request.done.json`으로 바꾼다. 요청 파일은 소비 측(재학습 DAG)이 폴링한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from app.CROWD.pipeline.retrain.common import (
    MONITORING_DIR,
    SCORE_DIR,
    SCORE_META_NAME,
    SCORE_PARQUET_NAME,
    now_kst,
    parse_generated_at,
    read_json,
    today_kst,
    write_json,
)
from app.CROWD.pipeline.retrain.stats import bootstrap_improvement, daily_losses

TARGETS = ("boarding", "alighting")
MIN_DATES = 7
COLS = ("actual", "pred", "lookup")
RECENT_DAYS = 14


# ── 채점 결과 읽기 ──
def _score_days(score_root: Path) -> list[tuple[pd.Timestamp, Path]]:
    found = []
    for path in sorted(Path(score_root).glob("dt=*")):
        try:
            day = pd.Timestamp(path.name.removeprefix("dt=")).normalize()
        except ValueError:
            continue
        if (path / SCORE_META_NAME).exists():
            found.append((day, path))
    return found


def scored_dates(score_root: Path) -> list[pd.Timestamp]:
    return [day for day, _ in _score_days(score_root)]


def load_score_metas(score_root: Path, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    """[start, end] 구간의 채점 메타(날짜 오름차순)."""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    metas = []
    for day, path in _score_days(score_root):
        if start <= day <= end:
            meta = read_json(path / SCORE_META_NAME)
            if meta is not None:
                metas.append(meta)
    return metas


def load_score_rows(score_root: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """[start, end] 구간 채점 행(part.parquet)을 이어 붙인다. 없으면 빈 프레임."""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    frames = [
        pd.read_parquet(path / SCORE_PARQUET_NAME)
        for day, path in _score_days(score_root)
        if start <= day <= end and (path / SCORE_PARQUET_NAME).exists()
    ]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ── R0 ──
def r0_data_hold(
    score_root: Path, today: pd.Timestamp, window_days: int = 28, max_missing: int = 7
) -> dict:
    """최근 `window_days`일(어제까지) 중 채점 결과가 없는 날이 `max_missing`일을 넘으면 hold."""
    today = pd.Timestamp(today).normalize()
    start = today - pd.Timedelta(days=window_days)
    end = today - pd.Timedelta(days=1)
    present = {d for d in scored_dates(score_root) if start <= d <= end}
    missing = window_days - len(present)
    return {
        "rule": "R0",
        "hold": missing > max_missing,
        "missing_days": int(missing),
        "window": [f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}"],
    }


# ── R1' ──
def r1_performance_alert(
    rows: pd.DataFrame,
    n_boot: int = 1000,
    seed: int = 0,
    baseline: dict | None = None,
    drop_pp: float = 5.0,
) -> dict:
    """가용성별·타깃별 모델 대 lookup 개선율 부트스트랩 → 경보 목록.

    반환 `{"alerts": [...], "skipped": [...], "groups": [...]}`. `groups`는 계산한 전 그룹이다.
    """
    alerts: list[dict] = []
    skipped: list[dict] = []
    groups: list[dict] = []
    needed = {"date", "availability", *(f"{t}_{k}" for t in TARGETS for k in COLS)}
    if rows.empty or not needed <= set(rows.columns):
        return {"alerts": alerts, "skipped": skipped, "groups": groups}

    frame = rows.copy()
    frame["availability"] = frame["availability"].fillna("unknown").astype(str)
    for availability, sub in frame.groupby("availability", sort=True):
        for target in TARGETS:
            cols = [f"{target}_actual", f"{target}_pred", f"{target}_lookup"]
            ok = sub[cols].notna().all(axis=1)
            clean = sub[ok]
            model = daily_losses(clean, f"{target}_pred", f"{target}_actual")
            base = daily_losses(clean, f"{target}_lookup", f"{target}_actual")
            n_dates = len(model)
            if n_dates < MIN_DATES:
                skipped.append(
                    {
                        "availability": availability,
                        "target": target,
                        "n_dates": int(n_dates),
                        "reason": f"날짜 {MIN_DATES}개 미만",
                    }
                )
                continue
            res = bootstrap_improvement(model, base, n_boot=n_boot, seed=seed)
            entry = {
                "availability": availability,
                "target": target,
                "point": res["point"],
                "ci_low": res["ci_low"],
                "ci_high": res["ci_high"],
                "n_dates": res["n_dates"],
            }
            reason = None
            if res["ci_high"] < 0:
                reason = "CI 상한이 0 미만(모델이 lookup보다 나쁨)"
            elif baseline is not None:
                ref = baseline.get(availability, {}).get(target)
                if ref is not None and res["point"] < ref - drop_pp:
                    reason = f"기준 {ref:+.2f}%에서 {drop_pp}%p 이상 하락"
            groups.append({**entry, "alert": reason is not None})
            if reason is not None:
                alerts.append({"rule": "R1'", **entry, "reason": reason})
    return {"alerts": alerts, "skipped": skipped, "groups": groups}


# ── R3 ──
def first_sunday(year: int, month: int) -> pd.Timestamp:
    first = pd.Timestamp(year=year, month=month, day=1)
    return first + pd.Timedelta(days=(6 - first.weekday()) % 7)


def is_first_sunday(date: pd.Timestamp) -> bool:
    date = pd.Timestamp(date).normalize()
    return date == first_sunday(date.year, date.month)


def r3_calendar_due(
    today: pd.Timestamp, state: dict | None, score_dates: list, min_new_days: int = 20
) -> dict:
    """첫 일요일 ∧ 마지막 후보 이후 채점일 ≥ `min_new_days`이면 due."""
    today = pd.Timestamp(today).normalize()
    last = (state or {}).get("last_candidate_date")
    if last:
        cut = pd.Timestamp(last).normalize()
        new_days = sum(1 for d in score_dates if pd.Timestamp(d).normalize() > cut)
    else:
        new_days = len(score_dates)
    sunday = is_first_sunday(today)
    due = bool(sunday and new_days >= min_new_days)
    if not sunday:
        reason = "첫 일요일이 아님"
    elif new_days < min_new_days:
        reason = f"신규 채점일 {new_days}일 < {min_new_days}일"
    else:
        reason = f"첫 일요일 · 신규 채점일 {new_days}일"
    return {
        "rule": "R3",
        "due": due,
        "is_first_sunday": bool(sunday),
        "new_scored_days": int(new_days),
        "last_candidate_date": last,
        "reason": reason,
    }


# ── 요청 파일 ──
def _sibling(path: Path, tag: str) -> Path:
    return path.with_name(f"{path.stem}.{tag}{path.suffix}")


def _as_kst(value) -> pd.Timestamp:
    return parse_generated_at(str(value))


def write_request(
    path: Path,
    *,
    rule: str,
    reason: str,
    target_date: pd.Timestamp,
    now: pd.Timestamp,
    ttl_days: int = 7,
) -> dict:
    created = _as_kst(now)
    request = {
        "rule": rule,
        "reason": reason,
        "date": f"{pd.Timestamp(target_date):%Y-%m-%d}",
        "created_at": created.isoformat(),
        "expires": (created + pd.Timedelta(days=ttl_days)).isoformat(),
    }
    write_json(path, request)
    return request


def read_request(path: Path, now: pd.Timestamp) -> tuple[dict | None, str]:
    """요청 파일을 읽는다. status: none / valid / expired(만료 파일은 `.expired.json`으로 개명)."""
    path = Path(path)
    request = read_json(path)
    if request is None:
        return None, "none"
    if _as_kst(request["expires"]) <= _as_kst(now):
        path.replace(_sibling(path, "expired"))
        return request, "expired"
    return request, "valid"


def mark_done(path: Path) -> Path:
    """처리가 끝난 요청 파일을 `.done.json`으로 개명하고 새 경로를 돌려준다."""
    path = Path(path)
    target = _sibling(path, "done")
    path.replace(target)
    return target


# ── 평가 ──
def evaluate(
    today: pd.Timestamp,
    *,
    score_root: Path = SCORE_DIR,
    monitoring_dir: Path = MONITORING_DIR,
    n_boot: int = 1000,
    seed: int = 0,
    baseline: dict | None = None,
    now: pd.Timestamp | None = None,
) -> dict:
    """R0 → (hold가 아니면) R1' → R3를 돌리고 `drift_latest.json`을 쓴다. R3 due면 요청 파일 생성."""
    today = pd.Timestamp(today).normalize()
    monitoring_dir = Path(monitoring_dir)
    # now를 안 주면 today 자정(KST)로 둔다 — 요청 TTL이 판정 기준일과 같은 시계를 쓰게 한다.
    now = _as_kst(now) if now is not None else _as_kst(today)

    r0 = r0_data_hold(score_root, today)
    if r0["hold"]:
        r1 = {"alerts": [], "skipped": [], "groups": [], "skipped_reason": "R0 hold"}
    else:
        rows = load_score_rows(
            score_root, today - pd.Timedelta(days=RECENT_DAYS), today - pd.Timedelta(days=1)
        )
        r1 = r1_performance_alert(rows, n_boot=n_boot, seed=seed, baseline=baseline)

    state = read_json(monitoring_dir / "retrain_state.json")
    r3 = r3_calendar_due(today, state, scored_dates(score_root))

    request_path = monitoring_dir / "retrain_request.json"
    existing, status = read_request(request_path, now)
    request_info = {"status": status, "written": False, "path": str(request_path)}
    if r3["due"] and status != "valid":
        request = write_request(
            request_path, rule="R3", reason=r3["reason"], target_date=today, now=now
        )
        request_info.update(status="valid", written=True, request=request)
    elif existing is not None and status == "valid":
        request_info["request"] = existing

    result = {
        "date": f"{today:%Y-%m-%d}",
        "generated_at": now.isoformat(),
        "r0": r0,
        "r1": r1,
        "r3": r3,
        "request": request_info,
    }
    write_json(monitoring_dir / "drift_latest.json", result)
    return result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="드리프트 판정(R0·R1'·R3)")
    ap.add_argument("--date", default=None, help="판정 기준일 YYYY-MM-DD (기본: 오늘 KST)")
    ap.add_argument("--score-dir", default=str(SCORE_DIR))
    ap.add_argument("--monitoring-dir", default=str(MONITORING_DIR))
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    today = pd.Timestamp(args.date).normalize() if args.date else today_kst()
    result = evaluate(
        today,
        score_root=Path(args.score_dir),
        monitoring_dir=Path(args.monitoring_dir),
        n_boot=args.n_boot,
        seed=args.seed,
        now=now_kst() if args.date is None else None,
    )
    r0, r1, r3, req = result["r0"], result["r1"], result["r3"], result["request"]
    print(
        f"[드리프트] {result['date']} R0 hold={r0['hold']} 결손 {r0['missing_days']}일", flush=True
    )
    print(f"[드리프트] R1' 경보 {len(r1['alerts'])}건 · 건너뜀 {len(r1['skipped'])}건", flush=True)
    print(f"[드리프트] R3 due={r3['due']} ({r3['reason']}) · 요청 {req['status']}", flush=True)
    # Discord 전송은 여기서 하지 않는다 — 웹훅 시크릿이 DAG 환경변수에만 있어서 stdout으로 넘기고
    # DAG가 `[ALERT]` 줄을 모아 보낸다.
    for a in r1["alerts"]:
        print(
            f"[ALERT] R1' {a['availability']}/{a['target']} "
            f"개선율 {a['point']:+.2f}% [CI {a['ci_low']:+.2f}, {a['ci_high']:+.2f}] — {a['reason']}",
            flush=True,
        )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
