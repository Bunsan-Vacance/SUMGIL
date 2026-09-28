"""323-4 — `POST /time/reroute/check` 배포 서버 성능 측정.

`run_local.py`(가짜 BE·가짜 LLM·가짜 색인)와 달리 이 스크립트는 **실제로 배포된 AI 서버**에
HTTP로 요청을 보낸다. 그래서:

- `--base-url`은 **필수**다(기본값 없음) — 잘못 짚어 운영 서버를 조용히 두드리는 일이 없게 한다.
- **작성만 하고 이 세션에서 실행하지 않는다**(`AI/CLAUDE.md` 대량·반복 호출 하드 룰과 같은 취지 —
  배포 서버에 반복 호출을 보내는 스크립트는 실행 범위를 사람과 먼저 맞춘다).
- 기본은 `no_trigger` 경로만 N회 두드린다. LLM(`proposal`) 경로는 `--with-proposal`을 **명시**
  해야 켜진다 — 실제 GMS 게이트웨이 호출이 섞여 과금·지연이 생기고, 서버의
  `time_debug_force_trigger_enabled` 운영 플래그가 꺼져 있으면(정상적인 운영 기본값,
  `router.py` 참고) `debugForceTrigger`가 무시되고 그냥 `no_trigger`로 응답한다는 점도 같이
  기억해야 한다.
- `--rental-id`·`--dest-station-id`는 **배포 서버가 실제로 아는 값**이어야 한다. 이 스크립트는
  값을 지어내지 않는다 — 존재하지 않는 ID를 넣으면 `target_unknown`/`unavailable`만 재게 된다.

이 스크립트는 `run_local.py`와 같은 지표(n·mean·p50·p95·min·max, status 분포)를 낸다. **LLM 지연
분해는 여기서 하지 않는다** — 실제 GMS 지연은 상수가 아니라서(`run_local.py`의 가짜 LLM과 달리)
표본에서 상수를 빼는 방식이 성립하지 않는다. LLM 자체 지연을 보려면 서버 로그(`llm.py`가 남기는
`latency_ms`)를 봐야 한다.

실행(사용 전 반드시 `--base-url`·`--rental-id`·`--dest-station-id`를 실제 값으로 맞출 것):
    cd AI
    python validation/TIME/latency-check/src/run_dev.py \\
        --base-url https://<배포 주소> --rental-id <실제 대여소 ID> \\
        --dest-station-id <실제 목적지 역 ID> --count 20
    # LLM 경로까지 보려면(운영 플래그가 켜져 있을 때만 의미 있음):
    python validation/TIME/latency-check/src/run_dev.py \\
        --base-url https://<배포 주소> --rental-id <실제 대여소 ID> \\
        --dest-station-id <실제 목적지 역 ID> --count 20 --with-proposal
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[3]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

KST = ZoneInfo("Asia/Seoul")
FE_TIMEOUT_SEC = 6.0
"""계약 기준(FE 타임아웃). README 참고."""

DEFAULT_TIMEOUT_SEC = 8.0
"""요청 타임아웃 — FE 기준(6초)보다 살짝 여유를 둬 "정말 안 오는지"와 "느린지"를 구분한다."""


@dataclass
class CallRecord:
    elapsed_sec: float
    status_code: int
    body_status: str | None
    error: str | None = None


def _one_call(
    session: requests.Session, url: str, payload: dict[str, Any], timeout_sec: float
) -> CallRecord:
    started = time.perf_counter()
    try:
        resp = session.post(url, json=payload, timeout=timeout_sec)
    except requests.RequestException as exc:
        elapsed = time.perf_counter() - started
        return CallRecord(
            elapsed_sec=elapsed, status_code=-1, body_status=None, error=type(exc).__name__
        )
    elapsed = time.perf_counter() - started
    body_status: str | None = None
    if resp.status_code == 200:
        try:
            body_status = resp.json().get("status")
        except ValueError:
            body_status = None
    return CallRecord(elapsed_sec=elapsed, status_code=resp.status_code, body_status=body_status)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    data = sorted(values)
    k = (len(data) - 1) * (pct / 100)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[f] + (data[c] - data[f]) * (k - f)


def summarize(records: list[CallRecord]) -> dict[str, Any]:
    elapsed_ms = [r.elapsed_sec * 1000.0 for r in records]
    return {
        "n": len(records),
        "mean_ms": round(sum(elapsed_ms) / len(elapsed_ms), 1) if elapsed_ms else None,
        "p50_ms": round(_percentile(elapsed_ms, 50), 1),
        "p95_ms": round(_percentile(elapsed_ms, 95), 1),
        "min_ms": round(min(elapsed_ms), 1) if elapsed_ms else None,
        "max_ms": round(max(elapsed_ms), 1) if elapsed_ms else None,
        "http_status_counts": dict(Counter(r.status_code for r in records)),
        "body_status_counts": dict(Counter(r.body_status for r in records)),
        "error_counts": dict(Counter(r.error for r in records if r.error is not None)),
    }


def to_markdown(*, base_url: str, count: int, concurrency: int, summary: dict[str, Any]) -> str:
    lines = [
        f"# 배포 서버 성능 측정 — {base_url}",
        "",
        f"count={count}, concurrency={concurrency}. FE 타임아웃 기준: {FE_TIMEOUT_SEC:.1f}초.",
        "",
        "| n | mean(ms) | p50(ms) | p95(ms) | min(ms) | max(ms) | HTTP 상태 분포 | body.status 분포 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        (
            f"| {summary['n']} | {summary['mean_ms']} | {summary['p50_ms']} "
            f"| {summary['p95_ms']} | {summary['min_ms']} | {summary['max_ms']} "
            f"| {summary['http_status_counts']} | {summary['body_status_counts']} |"
        ),
        "",
    ]
    if summary["error_counts"]:
        lines.append(f"요청 예외: {summary['error_counts']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="배포된 AI 서버 주소(필수, 기본값 없음)")
    parser.add_argument("--rental-id", required=True, help="배포 서버가 실제로 아는 대여소 ID")
    parser.add_argument(
        "--dest-station-id", required=True, help="배포 서버가 실제로 아는 목적지 역 ID"
    )
    parser.add_argument("--count", type=int, default=20, help="호출 횟수(no_trigger 경로)")
    parser.add_argument(
        "--concurrency", type=int, default=1, help="동시 호출 수(기본 1=순차 — 배포 서버 보호)"
    )
    parser.add_argument(
        "--eta-minutes", type=int, default=10, help="etaToRentalMinutes(기본값은 임의값이다)"
    )
    parser.add_argument("--step", type=int, default=0, help="step(기본값은 임의값이다)")
    parser.add_argument(
        "--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC, help="요청 타임아웃(초)"
    )
    parser.add_argument(
        "--with-proposal",
        action="store_true",
        help="debugForceTrigger=true로 LLM 경로까지 켠다(명시해야만 동작 — 모듈 docstring)",
    )
    parser.add_argument(
        "--boundary",
        type=str,
        default=None,
        help='JSON 문자열(예: \'{"legIndex":1,"nodeId":"ND-1","lat":37.5,"lng":127.0}\'). '
        "--with-proposal일 때 경로 연결(⑥)까지 보려면 필요 — 없으면 boundary_missing으로 끝난다.",
    )
    parser.add_argument("--out-dir", type=str, default=None, help="결과 저장 디렉터리(기본: out/)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else _HERE.parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    boundary = json.loads(args.boundary) if args.boundary else None

    url = f"{args.base_url.rstrip('/')}/time/reroute/check"

    def _payload(session_id: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "sessionId": session_id,
            "step": args.step,
            "rentalId": args.rental_id,
            "etaToRentalMinutes": args.eta_minutes,
            "destStationId": args.dest_station_id,
        }
        if boundary is not None:
            body["boundary"] = boundary
        if args.with_proposal:
            body["debugForceTrigger"] = True
        return body

    records: list[CallRecord] = []
    with requests.Session() as http_session:
        if args.concurrency <= 1:
            for _ in range(args.count):
                session_id = f"dev-{uuid.uuid4()}"
                records.append(_one_call(http_session, url, _payload(session_id), args.timeout_sec))
        else:
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                futures = [
                    executor.submit(
                        _one_call,
                        http_session,
                        url,
                        _payload(f"dev-{uuid.uuid4()}"),
                        args.timeout_sec,
                    )
                    for _ in range(args.count)
                ]
                for future in as_completed(futures):
                    records.append(future.result())

    summary = summarize(records)
    result = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "count": args.count,
        "concurrency": args.concurrency,
        "with_proposal": args.with_proposal,
        "fe_timeout_sec": FE_TIMEOUT_SEC,
        "summary": summary,
    }

    suffix = "proposal" if args.with_proposal else "no_trigger"
    stem = f"dev_{suffix}_n{args.count}_c{args.concurrency}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        to_markdown(
            base_url=args.base_url, count=args.count, concurrency=args.concurrency, summary=summary
        ),
        encoding="utf-8",
    )

    print(f"[저장] {json_path}")
    print(f"[저장] {md_path}")
    print(f"p50={summary['p50_ms']}ms p95={summary['p95_ms']}ms n={summary['n']}")


if __name__ == "__main__":
    main()
