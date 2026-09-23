"""323-4 — `POST /time/reroute/check` 로컬 성능 측정(가짜 BE·가짜 LLM·가짜 색인).

세션 N개가 120초 폴링 주기를 흉내내 **동시에** 이 엔드포인트를 부를 때 `no_trigger`(평소 상태)
경로와 `proposal`(`debugForceTrigger`로 강제) 경로 각각의 응답 시간을 잰다. 실제 BE·GMS
게이트웨이는 부르지 않는다 — `router.py`의 모듈 레벨 팩토리(`_station_index`·`_adapter`·
`_strategy`·`_now`·`get_settings`)를 `test/TIME/test_time_router.py`와 같은 방식으로
monkeypatch해서 갈아끼운다(재사용: `FakeAdapter`·`InMemoryStationIndex`·`RuleStrategy` 패턴).

**LLM 지연은 고정값이다.** `FakeLlmClient.complete()`가 `time.sleep(delay_sec)`만 하고 정해진
JSON을 돌려주므로, `proposal` 경로의 표본 각각에서 `delay_sec`를 그대로 빼면 "LLM을 뺀 나머지
처리 시간"이 나온다(고정 지연이라 근사가 아니라 정확한 뺄셈이다). 이것이 README가 말하는
"LLM 지연 분해"다.

**세션 ID는 라운드·인덱스로 매번 새로 만든다** — 쿨다운(`time_trigger_cooldown_sec`, 기본
600초)이 같은 세션의 반복 폴링을 막는 실제 동작인데, 그 로직 자체는 이 성능 측정의 관심사가
아니다. 세션 ID를 겹치지 않게 하면 모든 요청이 매번 "처음 보는 세션"이라 쿨다운이 결과를
왜곡하지 않는다.

실행(폴더명에 하이픈이 있어 파일 경로 호출):
    cd AI
    python validation/TIME/latency-check/src/run_local.py --sessions 10 --rounds 1
    python validation/TIME/latency-check/src/run_local.py --sessions 50 --rounds 3
    python validation/TIME/latency-check/src/run_local.py --sessions 100 --rounds 3

결과는 `--out-dir`(기본: 이 스크립트 옆 `out/`)에 `local_s<세션>_r<라운드>.md`·`.json`으로 쌓인다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[3]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from fastapi.testclient import TestClient

from app.main import app
from app.TIME import router as router_mod
from app.TIME.llm import LlmOutcome, LlmResult
from app.TIME.llm_budget import LlmBudget
from app.TIME.registry import GET_ETA_STOCK, REPLAN_ROUTE
from app.TIME.schemas import ToolError
from app.TIME.station_index import InMemoryStationIndex, RentalStation
from app.TIME.strategy import AgentStrategy, RuleStrategy

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 9, 23, 9, 0, tzinfo=KST)
"""고정 시각 — `router._now`를 여기로 갈아끼운다. 쿨다운 판정에만 쓰이고 세션 ID가 매번
새로우므로(모듈 docstring) 값 자체는 결과에 영향이 없다."""

FE_TIMEOUT_SEC = 6.0
"""계약 기준(FE 타임아웃). README 참고 — 이 스크립트의 수치를 이 값과 비교해 읽는다."""

TARGET_ID = "LC-TARGET"
ALT1_ID = "LC-ALT-1"
ALT2_ID = "LC-ALT-2"
DEST_ID = "LC-DEST"
BOUNDARY_PAYLOAD = {"legIndex": 1, "nodeId": "ND-LC", "lat": 37.5665, "lng": 126.9780}


# ── 가짜 색인(`test_time_router.py`의 `InMemoryStationIndex` 사용법과 같다) ──


def _station(rental_id: str, *, lat: float, lng: float, name: str) -> RentalStation:
    return RentalStation(
        rental_id=rental_id,
        name=name,
        lat=lat,
        lng=lng,
        rack_count=10,
        current_stock=5,
        updated_at=None,
    )


TARGET_STATION = _station(TARGET_ID, lat=37.5665, lng=126.9780, name="LC-타겟")
ALT1_STATION = _station(ALT1_ID, lat=37.5666, lng=126.9780, name="LC-대안1")  # 대상에서 ~11m
ALT2_STATION = _station(ALT2_ID, lat=37.5667, lng=126.9780, name="LC-대안2")  # 대상에서 ~22m
# 후보가 2개 이상이어야 `AgentStrategy.decide`가 LLM을 실제로 부른다(후보 1개면 규칙으로
# 바로 폴백 — `strategy.py` `AgentStrategy.decide` 참고). 프록시 지연 분해가 목적이라 반드시 2개.
STATION_INDEX = InMemoryStationIndex([TARGET_STATION, ALT1_STATION, ALT2_STATION])


# ── 가짜 재고 읽기(`test_time_router.py`의 `_eta()` 헬퍼와 같은 모양) ──


def _eta(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "rental_id": "X",
        "eta_minutes": 10,
        "current_stock": 0,
        "predicted_stock": 0.3,
        "p_empty": 0.9,
        "p_full": 0.0,
        "source": "lightgbm",
        "model_horizon_min": 10,
    }
    body.update(overrides)
    return body


FIRED_TARGET = _eta(current_stock=0, predicted_stock=0.3, p_empty=0.9)
BELOW_THRESHOLD_TARGET = _eta(current_stock=5, predicted_stock=5.0, p_empty=0.1)
GOOD_ALT = _eta(current_stock=4, predicted_stock=4.0, p_empty=0.1)


def _route_element() -> dict[str, Any]:
    return {
        "reason": "BE 고정 문구",
        "source": "ALGORITHM",
        "route": {
            "routeType": "BIKE_SUBWAY",
            "totalMinutes": 20.0,
            "source": "ALGORITHM",
            "totalDistanceMeters": 6000.0,
            "transferCount": 0,
            "legs": [{"mode": "BIKE", "minutes": 20.0, "routeId": None}],
        },
    }


class FakeAdapter:
    """`test_time_router.py`의 `FakeAdapter`와 같은 모양 — 가짜 BE. `get_eta_stock`은
    rental_id별 고정 응답을, `replan_route`는 고정 성공 응답을 즉시(지연 없이) 낸다."""

    def __init__(self, *, eta_stock: dict[str, Any] | None = None, replan: Any = None) -> None:
        self.eta_stock = dict(eta_stock or {})
        self.replan = [_route_element()] if replan is None else replan

    def call(self, name: str, args: dict[str, Any]) -> Any:
        if name == GET_ETA_STOCK:
            rental_id = str(args["rental_id"])
            if rental_id not in self.eta_stock:
                return ToolError.not_found(f"{rental_id} 실시간 재고를 확인할 수 없다")
            return self.eta_stock[rental_id]
        if name == REPLAN_ROUTE:
            return self.replan
        return ToolError.invalid_input(f"가짜 어댑터가 모르는 도구 '{name}'")


NO_TRIGGER_ADAPTER = FakeAdapter(eta_stock={TARGET_ID: BELOW_THRESHOLD_TARGET})
PROPOSAL_ADAPTER = FakeAdapter(
    eta_stock={TARGET_ID: FIRED_TARGET, ALT1_ID: GOOD_ALT, ALT2_ID: GOOD_ALT}
)


# ── 가짜 LLM ──

_TARGET_NAME_RE = re.compile(r"^- 대여소: (.+)$", re.MULTILINE)
_CANDIDATE0_NAME_RE = re.compile(r"^0\. (.+?) — ", re.MULTILINE)


def _extract_target_name(user_prompt: str) -> str:
    m = _TARGET_NAME_RE.search(user_prompt)
    return m.group(1).strip() if m else "이 대여소"


def _extract_candidate0_name(user_prompt: str) -> str:
    m = _CANDIDATE0_NAME_RE.search(user_prompt)
    return m.group(1).strip() if m else "대안 대여소"


@dataclass
class FakeLlmClient:
    """`llm.LlmClient` 프로토콜 구현 — 실제 GMS 게이트웨이 대신 고정 지연만 흉내낸다.

    숫자를 아예 안 쓰는 문장을 만든다 — `AgentStrategy`의 환각 검사(`_allowed_numbers`)가
    "프롬프트에 나온 숫자만 허용"이라 숫자를 새로 안 쓰면 그 검사를 항상 통과한다. 목적은
    LLM 응답 검증 로직 테스트가 아니라 **지연 측정**이라, 검증 통과가 안정적이어야 표본이
    전부 `proposal`로 끝나 지연 분해가 깨끗하게 나온다.
    """

    delay_sec: float = 1.2

    def complete(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LlmOutcome:
        started = time.monotonic()
        time.sleep(self.delay_sec)
        elapsed_ms = (time.monotonic() - started) * 1000.0

        target_name = _extract_target_name(user)
        alt_name = _extract_candidate0_name(user)
        reason = f"{target_name}은 곧 자전거가 없을 것으로 보입니다. {alt_name}로 이동해 보세요."
        text = json.dumps({"chosen_index": 0, "reason": reason}, ensure_ascii=False)
        return LlmResult(
            text=text,
            input_tokens=None,
            output_tokens=None,
            latency_ms=elapsed_ms,
            model="fake-gms-mini",
        )


# ── 가짜 설정(`test_time_router.py`의 `_FakeSettings`와 같은 필드) ──


class _FakeSettings:
    def __init__(self, **overrides: Any) -> None:
        base: dict[str, Any] = {
            "time_be_base_url": None,
            "time_be_timeout_sec": 3.0,
            "time_trigger_cooldown_sec": 600.0,
            "time_recommendation_ttl_sec": 600.0,
            "time_debug_force_trigger_enabled": False,
            "time_nearby_radius_m": 500,
            "time_nearby_limit": 5,
            "time_trigger_p_empty": 0.7,
            "time_trigger_min_stock": 1.0,
            "time_trigger_max_eta_min": 30,
            "time_score_empty_penalty_min": 10.0,
            "time_llm_base_url": None,
            "time_llm_model": None,
            "time_llm_api_key": None,
            "time_llm_max_calls_per_session": 3,
            "time_llm_max_tokens_per_session": 8000,
            "time_agent_reason_max_sentences": 2,
            "time_agent_reason_max_chars": 120,
        }
        base.update(overrides)
        for key, value in base.items():
            setattr(self, key, value)


# ── 측정 루프 ──


@dataclass
class CallRecord:
    elapsed_sec: float
    status: str | None
    recommended_by: str | None


def _one_call(client: TestClient, payload: dict[str, Any]) -> CallRecord:
    started = time.perf_counter()
    resp = client.post("/time/reroute/check", json=payload)
    elapsed = time.perf_counter() - started
    body = resp.json() if resp.status_code == 200 else {}
    return CallRecord(
        elapsed_sec=elapsed, status=body.get("status"), recommended_by=body.get("recommendedBy")
    )


def measure_path(
    client: TestClient,
    executor: ThreadPoolExecutor,
    *,
    session_prefix: str,
    sessions: int,
    rounds: int,
    payload_template: dict[str, Any],
) -> list[CallRecord]:
    """`sessions`개 세션이 한 라운드에 동시에 폴링하는 것을 `rounds`번 반복한다.

    라운드 사이에 실제 120초를 기다리지 않는다 — 이 스크립트는 "그 순간 동시에 몰리면"을 재는
    부하 측정이지, 실시간 흐름 재현이 목적이 아니다(README 참고).
    """
    records: list[CallRecord] = []
    for r in range(rounds):
        payloads = []
        for i in range(sessions):
            body = dict(payload_template)
            body["sessionId"] = f"{session_prefix}-r{r}-s{i}"
            payloads.append(body)
        futures = [executor.submit(_one_call, client, p) for p in payloads]
        for future in as_completed(futures):
            records.append(future.result())
    return records


# ── 통계 ──


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
        "status_counts": dict(Counter(r.status for r in records)),
        "recommended_by_counts": dict(Counter(r.recommended_by for r in records)),
    }


def summarize_with_llm_decomposition(
    records: list[CallRecord], llm_delay_sec: float
) -> dict[str, Any]:
    """`proposal` 표본에서 "전체 − LLM"을 뺀 값의 분포를 추가로 낸다.

    LLM 지연이 상수(`FakeLlmClient.delay_sec`)라 표본마다 그대로 빼면 된다 — 근사가 아니라
    정확한 뺄셈이다(모듈 docstring).
    """
    summary = summarize(records)
    proposal_only = [r for r in records if r.status == "proposal"]
    overhead_ms = [r.elapsed_sec * 1000.0 - llm_delay_sec * 1000.0 for r in proposal_only]
    summary["llm_decomposition"] = {
        "llm_fixed_delay_ms": round(llm_delay_sec * 1000.0, 1),
        "n_proposal": len(proposal_only),
        "overhead_p50_ms": round(_percentile(overhead_ms, 50), 1) if overhead_ms else None,
        "overhead_p95_ms": round(_percentile(overhead_ms, 95), 1) if overhead_ms else None,
        "overhead_mean_ms": (
            round(sum(overhead_ms) / len(overhead_ms), 1) if overhead_ms else None
        ),
    }
    return summary


# ── 출력 ──


def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def to_markdown(*, sessions: int, rounds: int, no_trigger: dict, proposal: dict) -> str:
    lines = [
        f"# 로컬 성능 측정 — sessions={sessions}, rounds={rounds}",
        "",
        f"FE 타임아웃 기준: {FE_TIMEOUT_SEC:.1f}초. 아래 p95(ms)를 이 기준과 비교해 읽는다.",
        "",
        "## no_trigger 경로",
        "",
        "| n | mean(ms) | p50(ms) | p95(ms) | min(ms) | max(ms) | status 분포 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        (
            f"| {no_trigger['n']} | {_fmt(no_trigger['mean_ms'])} | {_fmt(no_trigger['p50_ms'])} "
            f"| {_fmt(no_trigger['p95_ms'])} | {_fmt(no_trigger['min_ms'])} "
            f"| {_fmt(no_trigger['max_ms'])} | {no_trigger['status_counts']} |"
        ),
        "",
        "## proposal 경로(`debugForceTrigger`)",
        "",
        "| n | mean(ms) | p50(ms) | p95(ms) | min(ms) | max(ms) | status 분포 | recommendedBy 분포 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        (
            f"| {proposal['n']} | {_fmt(proposal['mean_ms'])} | {_fmt(proposal['p50_ms'])} "
            f"| {_fmt(proposal['p95_ms'])} | {_fmt(proposal['min_ms'])} "
            f"| {_fmt(proposal['max_ms'])} | {proposal['status_counts']} "
            f"| {proposal['recommended_by_counts']} |"
        ),
        "",
        "### LLM 지연 분해(전체 − LLM 고정 지연)",
        "",
        (
            "| LLM 고정 지연(ms) | 표본(proposal만) | 전체 p50(ms) | 전체 p95(ms) "
            "| 오버헤드 p50(ms) | 오버헤드 p95(ms) |"
        ),
        "| --- | --- | --- | --- | --- | --- |",
        (
            f"| {proposal['llm_decomposition']['llm_fixed_delay_ms']} "
            f"| {proposal['llm_decomposition']['n_proposal']} "
            f"| {_fmt(proposal['p50_ms'])} | {_fmt(proposal['p95_ms'])} "
            f"| {_fmt(proposal['llm_decomposition']['overhead_p50_ms'])} "
            f"| {_fmt(proposal['llm_decomposition']['overhead_p95_ms'])} |"
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=50, help="동시 세션 수(권장: 10/50/100)")
    parser.add_argument("--rounds", type=int, default=3, help="반복 폴링 라운드 수(표본 확보용)")
    parser.add_argument(
        "--llm-delay-sec", type=float, default=1.2, help="가짜 LLM 고정 지연(초, 실측 GMS 근사)"
    )
    parser.add_argument(
        "--max-workers", type=int, default=None, help="스레드풀 크기(기본: sessions)"
    )
    parser.add_argument(
        "--out-dir", type=str, default=None, help="결과 저장 디렉터리(기본: 스크립트 옆 out/)"
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else _HERE.parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    max_workers = args.max_workers or args.sessions

    no_trigger_payload = {
        "step": 0,
        "rentalId": TARGET_ID,
        "etaToRentalMinutes": 10,
        "destStationId": DEST_ID,
        "boundary": BOUNDARY_PAYLOAD,
    }
    proposal_payload = {**no_trigger_payload, "debugForceTrigger": True}

    with TestClient(app) as client:
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            # ── no_trigger 경로 ──
            router_mod._session_store_singleton = None
            router_mod.get_settings = lambda: _FakeSettings(time_debug_force_trigger_enabled=False)
            router_mod._station_index = lambda: STATION_INDEX
            router_mod._adapter = lambda: NO_TRIGGER_ADAPTER
            # `_strategy`는 세션 단위 LLM 예산(324-3)을 위해 `session_id`를 받는다
            # (`router.py` 모듈 docstring) — 이 스크립트는 세션마다 예산을 새로 만들 뿐이라
            # 인자는 받되 쓰지 않는다.
            router_mod._strategy = lambda session_id: RuleStrategy()
            router_mod._now = lambda: NOW

            no_trigger_records = measure_path(
                client,
                executor,
                session_prefix="lc-notrig",
                sessions=args.sessions,
                rounds=args.rounds,
                payload_template=no_trigger_payload,
            )

            # ── proposal 경로 ──
            router_mod._session_store_singleton = None
            router_mod.get_settings = lambda: _FakeSettings(time_debug_force_trigger_enabled=True)
            router_mod._adapter = lambda: PROPOSAL_ADAPTER
            fake_llm = FakeLlmClient(delay_sec=args.llm_delay_sec)
            router_mod._strategy = lambda session_id: AgentStrategy(
                fake_llm,
                fallback=RuleStrategy(),
                budget=LlmBudget(max_calls=3, max_total_tokens=8000),
                max_sentences=2,
                max_chars=120,
            )

            proposal_records = measure_path(
                client,
                executor,
                session_prefix="lc-prop",
                sessions=args.sessions,
                rounds=args.rounds,
                payload_template=proposal_payload,
            )
        finally:
            executor.shutdown(wait=True)

    no_trigger_summary = summarize(no_trigger_records)
    proposal_summary = summarize_with_llm_decomposition(proposal_records, args.llm_delay_sec)

    result = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "sessions": args.sessions,
        "rounds": args.rounds,
        "llm_delay_sec": args.llm_delay_sec,
        "fe_timeout_sec": FE_TIMEOUT_SEC,
        "no_trigger": no_trigger_summary,
        "proposal": proposal_summary,
    }

    stem = f"local_s{args.sessions}_r{args.rounds}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        to_markdown(
            sessions=args.sessions,
            rounds=args.rounds,
            no_trigger=no_trigger_summary,
            proposal=proposal_summary,
        ),
        encoding="utf-8",
    )

    print(f"[저장] {json_path}")
    print(f"[저장] {md_path}")
    print(
        f"no_trigger p50={no_trigger_summary['p50_ms']}ms p95={no_trigger_summary['p95_ms']}ms "
        f"| proposal p50={proposal_summary['p50_ms']}ms p95={proposal_summary['p95_ms']}ms "
        f"(오버헤드 p50={proposal_summary['llm_decomposition']['overhead_p50_ms']}ms "
        f"p95={proposal_summary['llm_decomposition']['overhead_p95_ms']}ms)"
    )


if __name__ == "__main__":
    main()
