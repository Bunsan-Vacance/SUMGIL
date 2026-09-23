"""`AgentContext` 직렬화(S15P21A104-331) — `build_samples.py`가 쓰고 `compare.py`가 읽는다.

`AgentContext`(`app.TIME.context`)는 표본 파일에 그대로 저장할 수 없는 값(예: `RentalStation.
updated_at`의 `datetime`)을 포함한다. 이 모듈은 그 구조를 JSON 안전한 dict로 뒤집고(`to_json`)
되돌리는(`from_json`) 왕복만 한다 — 값을 가공하거나 지어내지 않는다. 왕복 대상은 두 전략
(`RuleStrategy`·`AgentStrategy`)이 `decide()`에서 실제로 읽는 필드 전부다 — 표본 파일만 보고도
`AI/app` 없이는 아니지만 실제 트리거·프리페치 없이 두 전략을 그대로 태울 수 있어야 한다.

`app/TIME`을 import하므로 실행 시 `AI_ROOT`가 `sys.path`에 있어야 한다(`build_samples.py`·
`compare.py`가 먼저 넣는다). 이 모듈 자체는 경로를 건드리지 않는다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.TIME.context import AgentContext, CandidateContext, RentalCandidate
from app.TIME.station_index import RentalStation
from app.TIME.trigger import StockReading, TriggerResult


def _station_to_json(station: RentalStation) -> dict[str, Any]:
    return {
        "rental_id": station.rental_id,
        "name": station.name,
        "lat": station.lat,
        "lng": station.lng,
        "rack_count": station.rack_count,
        "current_stock": station.current_stock,
        "updated_at": station.updated_at.isoformat() if station.updated_at is not None else None,
    }


def _station_from_json(data: dict[str, Any]) -> RentalStation:
    updated_at = data.get("updated_at")
    return RentalStation(
        rental_id=data["rental_id"],
        name=data.get("name"),
        lat=data["lat"],
        lng=data["lng"],
        rack_count=data.get("rack_count"),
        current_stock=data.get("current_stock"),
        updated_at=datetime.fromisoformat(updated_at) if updated_at else None,
    )


def _reading_to_json(reading: StockReading | None) -> dict[str, Any] | None:
    if reading is None:
        return None
    return {
        "current_stock": reading.current_stock,
        "predicted_stock": reading.predicted_stock,
        "p_empty": reading.p_empty,
        "p_full": reading.p_full,
        "source": reading.source,
        "model_horizon_min": reading.model_horizon_min,
    }


def _reading_from_json(data: dict[str, Any] | None) -> StockReading | None:
    if data is None:
        return None
    return StockReading(
        current_stock=data.get("current_stock"),
        predicted_stock=data.get("predicted_stock"),
        p_empty=data.get("p_empty"),
        p_full=data.get("p_full"),
        source=data.get("source"),
        model_horizon_min=data.get("model_horizon_min"),
    )


def _candidate_ctx_to_json(ctx: CandidateContext) -> dict[str, Any]:
    return {
        "station": _station_to_json(ctx.candidate.station),
        "distance_m": ctx.candidate.distance_m,
        "reading": _reading_to_json(ctx.reading),
        "error": ctx.error,
    }


def _candidate_ctx_from_json(data: dict[str, Any]) -> CandidateContext:
    return CandidateContext(
        candidate=RentalCandidate(
            station=_station_from_json(data["station"]), distance_m=data["distance_m"]
        ),
        reading=_reading_from_json(data.get("reading")),
        error=data.get("error"),
    )


def to_json(ctx: AgentContext) -> dict[str, Any]:
    """`AgentContext` 하나를 JSON 안전한 dict로."""
    return {
        "decision": {
            "fired": ctx.decision.fired,
            "reason": ctx.decision.reason,
            "facts": ctx.decision.facts,
        },
        "target": _station_to_json(ctx.target),
        "target_reading": _reading_to_json(ctx.target_reading),
        "eta_minutes": ctx.eta_minutes,
        "candidates": [_candidate_ctx_to_json(c) for c in ctx.candidates],
        "dest_station_id": ctx.dest_station_id,
    }


def from_json(data: dict[str, Any]) -> AgentContext:
    """`to_json()`의 역변환. `target_reading`은 `AgentContext`에서 필수(non-optional)라
    표본 파일에 없으면 그 자체가 표본 생성 버그라 즉시 `KeyError`/`AssertionError`로 드러낸다
    (조용히 `None`을 넣어 넘어가지 않는다)."""
    decision_data = data["decision"]
    target_reading = _reading_from_json(data["target_reading"])
    if target_reading is None:
        raise ValueError("target_reading이 없는 표본이다 — AgentContext 불변식 위반")
    return AgentContext(
        decision=TriggerResult(
            fired=decision_data["fired"],
            reason=decision_data["reason"],
            facts=decision_data.get("facts", {}),
        ),
        target=_station_from_json(data["target"]),
        target_reading=target_reading,
        eta_minutes=data["eta_minutes"],
        candidates=[_candidate_ctx_from_json(c) for c in data.get("candidates", [])],
        dest_station_id=data.get("dest_station_id"),
    )


def write_samples(records: list[dict[str, Any]], path: Path) -> None:
    """표본 레코드 목록(각 레코드는 `{"id", "label", "description", "context": to_json(...)}`
    형태)을 JSON 파일 하나로 쓴다. 메타(`id`·`label`·`description`)를 붙이는 자리는
    `build_samples.py`가 정한다 — 이 함수는 이미 만들어진 dict를 그대로 파일로 옮길 뿐이다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def read_samples(path: Path) -> list[dict[str, Any]]:
    """`write_samples()`가 쓴 파일을 그대로 읽는다. `context` 필드는 아직 `AgentContext`로
    변환하지 않은 raw dict다 — 호출자가 필요할 때 `from_json(record["context"])`으로 바꾼다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"표본 파일 형식이 리스트가 아니다: {path}")
    return data


__all__ = [
    "from_json",
    "read_samples",
    "to_json",
    "write_samples",
]
