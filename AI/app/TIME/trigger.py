"""따릉이 재고 고갈 트리거 판정(S15P21A104-203/302).

**입력이 대여소 재고로 바뀌었다.** 이전 판(CROWD 혼잡 급등 — 등급/퍼센트 상승·최소 연속 구간)은
`AI/app/TIME/AGENT_DESIGN.md` 2.2절 결정에 따라 폐기했다. 재안내의 실제 방아쇠는 "안내 중 경로의
따릉이 대여소가 도착 시점에 비어 있을 것으로 예측되는가"다.

**LLM을 쓰지 않는다.** 트리거는 이동 중 매 폴링마다 돌아가므로, 여기에 LLM을 넣으면 대부분의
호출이 "아무 일도 없음"을 확인하는 데 초당 비용을 쓴다(멘토 조언 9.14 — 가공 데이터에서는
통계·규칙이 AI보다 나을 수 있으니 억지로 넣지 말 것).

**순수 함수다.** `get_eta_stock` 조회는 호출자(`planner.py`)가 하고 여기는 읽은 값(`StockReading`)만
받는다. 그래야 ① 테스트가 실제 parquet·모델 아티팩트 없이 돌고, ② 규칙 기준선과 LLM 에이전트가
**완전히 같은 입력**으로 판정하는 것이 보장된다(`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번).

## 규칙 순서 — 먼저 맞는 것이 이긴다

1. `stock_unknown` — 도구가 `ToolError`를 냈다. **"물어보지 못했다"를 "비었다"로 읽지 않는다**
   (`TOOL_CONTRACT.md` 2.1절 `NOT_FOUND`/`UPSTREAM_UNAVAILABLE` 구분의 트리거 층 반영). 호출자는
   이 사유를 `unavailable`로 옮긴다.
2. `horizon_out_of_range` — ETA가 상한을 넘었거나 모델이 실제로 예측한 horizon을 모른다
   (`model_horizon_min`이 없음). 학습 horizon 밖 예측을 근거로 쓰지 않는다.
3. `low_confidence` — 학습에 없던 신규 대여소라 전역 평균으로 낸 값(`lightgbm_global_fallback`).
   정확도가 낮아 트리거 근거로 쓰지 않는다.
4. `cooldown` — 같은 이동에서 팝업이 반복해 뜨는 것을 막는다.
5. `forced` — 디버그 강제 트리거(`debugForceTrigger`). 1~4는 **그대로 지킨다** — 오류·모름·
   신뢰 불가 상태까지 강제로 덮어쓰면 개발 편의가 데이터 무결성을 해친다. 허용 여부(운영 환경
   차단)는 이 함수가 아니라 호출자가 정한다(`time_debug_force_trigger_enabled`).
6. `p_empty` / `low_predicted_stock` — 실제 고갈 판정. `p_empty`를 먼저 본다(분류기가 있으면 더
   직접적인 신호). 없거나 임계 미만이면 `predicted_stock`으로 폴백한다. **`None`은 0이 아니다** —
   값이 없는 필드는 그 조건에서 빠질 뿐 고갈로도 여유로도 세지 않는다.
7. `below_threshold` — 나머지 전부. 평소 상태다.

이 순서 자체가 값 안 지어내기 원칙이다 — 오류(1)·모름(2)·신뢰 불가(3)를 먼저 걸러낸 뒤에만
"비었다"(6)를 판정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.TIME.schemas import ToolError

# 신뢰할 수 없는 예측 출처. `TOOL_CONTRACT.md` 3.2절 `source` 설명과 같다.
SOURCE_GLOBAL_FALLBACK = "lightgbm_global_fallback"


@dataclass(frozen=True)
class StockReading:
    """`get_eta_stock` 도구 결과에서 트리거 판정에 쓰는 필드만 옮겨 담은 값.

    호출자(`planner.py`)가 `ToolResult`(성공 시 dict, 실패 시 `ToolError`)에서 이 값 또는
    `ToolError`를 만들어 `evaluate`에 넘긴다. 필드는 전부 **선택**이다 — 도구 응답이 일부만
    채워진 경우에도 여기서 죽지 않고, `evaluate`가 값 유무에 따라 규칙을 가른다.
    """

    current_stock: int | None
    predicted_stock: float | None
    p_empty: float | None
    p_full: float | None
    source: str | None
    model_horizon_min: int | None


@dataclass(frozen=True)
class Thresholds:
    """`Settings`의 `time_trigger_*`를 담는다. 전부 **잠정값**이다 — `config.py` 주석 참고."""

    p_empty: float = 0.7
    min_stock: float = 1.0
    max_eta_min: int = 30
    cooldown_sec: float = 600.0

    @classmethod
    def from_settings(cls, settings: object) -> Thresholds:
        return cls(
            p_empty=getattr(settings, "time_trigger_p_empty", 0.7),
            min_stock=getattr(settings, "time_trigger_min_stock", 1.0),
            max_eta_min=getattr(settings, "time_trigger_max_eta_min", 30),
            cooldown_sec=getattr(settings, "time_trigger_cooldown_sec", 600.0),
        )


# 판정 사유. 트리거·비트리거 양쪽 다 이 값 하나(`TriggerResult.reason`)에 담긴다 — "왜 안 떴나"와
# "왜 떴나"를 같은 칸에서 다루면 디버깅·204 평가 하네스가 사유 하나만 보면 된다.
REASON_STOCK_UNKNOWN = "stock_unknown"
REASON_HORIZON_OUT_OF_RANGE = "horizon_out_of_range"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_COOLDOWN = "cooldown"
REASON_FORCED = "forced"
REASON_P_EMPTY = "p_empty"
REASON_LOW_PREDICTED_STOCK = "low_predicted_stock"
REASON_BELOW_THRESHOLD = "below_threshold"


@dataclass(frozen=True)
class TriggerResult:
    """판정 결과. `facts`는 안내 문장(규칙 템플릿·LLM 모두)이 인용할 **사실만** 담는다.

    트리거되지 않으면 `facts`는 비어 있다 — 근거로 쓸 값이 없다는 뜻이지 빈 딕셔너리를
    지어내는 것이 아니다.
    """

    fired: bool
    reason: str
    facts: dict[str, object] = field(default_factory=dict)


def evaluate(
    reading: StockReading | ToolError,
    *,
    eta_minutes: int,
    seconds_since_last_fire: float | None = None,
    thresholds: Thresholds | None = None,
    force: bool = False,
) -> TriggerResult:
    """대상 대여소가 도착 시점에 비어 있을 것으로 예측되는지 판정한다.

    규칙은 모듈 docstring의 순서대로 **먼저 맞는 것이 이긴다.** `force=True`는 5번 자리에서만
    끼어들고, 1~4번(오류·horizon·신뢰도·쿨다운)은 그대로 지킨다 — 강제 트리거라도 값을 지어내진
    않는다. `force` 허용 여부(운영 환경 차단) 자체는 호출자가 판단한다.
    """
    limits = thresholds or Thresholds()

    # 1) 도구 오류 — "비었다"가 아니라 "물어보지 못했다".
    if isinstance(reading, ToolError):
        return TriggerResult(fired=False, reason=REASON_STOCK_UNKNOWN)

    # 2) ETA가 학습 horizon 밖이거나, 모델이 실제로 어느 horizon을 썼는지 모른다.
    if eta_minutes > limits.max_eta_min or reading.model_horizon_min is None:
        return TriggerResult(fired=False, reason=REASON_HORIZON_OUT_OF_RANGE)

    # 3) 신규 대여소라 전역 평균으로 낸 값 — 트리거 근거로 쓰기엔 정확도가 낮다.
    if reading.source == SOURCE_GLOBAL_FALLBACK:
        return TriggerResult(fired=False, reason=REASON_LOW_CONFIDENCE)

    # 4) 같은 이동에서 팝업이 반복해 뜨는 것을 막는다.
    if seconds_since_last_fire is not None and seconds_since_last_fire < limits.cooldown_sec:
        return TriggerResult(fired=False, reason=REASON_COOLDOWN)

    # 5) 강제 트리거(dev 전용 debugForceTrigger). 1~4를 통과한 뒤에만 끼어든다.
    if force:
        return TriggerResult(fired=True, reason=REASON_FORCED, facts=_facts(reading, eta_minutes))

    # 6) 실제 고갈 판정. None은 0이 아니므로 값이 있을 때만 조건에 넣는다.
    if reading.p_empty is not None and reading.p_empty >= limits.p_empty:
        return TriggerResult(fired=True, reason=REASON_P_EMPTY, facts=_facts(reading, eta_minutes))
    if reading.predicted_stock is not None and reading.predicted_stock <= limits.min_stock:
        return TriggerResult(
            fired=True, reason=REASON_LOW_PREDICTED_STOCK, facts=_facts(reading, eta_minutes)
        )

    # 7) 나머지 전부 — 평소 상태.
    return TriggerResult(fired=False, reason=REASON_BELOW_THRESHOLD)


def _facts(reading: StockReading, eta_minutes: int) -> dict[str, object]:
    """안내 문장이 인용할 사실. **여기 없는 숫자는 문장에 쓰지 않는다.**

    규칙 템플릿과 LLM이 같은 사실 집합을 보게 해서, 둘의 차이가 '표현'에서만 나오고 '근거'에서는
    나오지 않도록 한다(7절 비교의 동등 조건).
    """
    return {
        "eta_minutes": eta_minutes,
        "current_stock": reading.current_stock,
        "predicted_stock": reading.predicted_stock,
        "p_empty": reading.p_empty,
        "p_full": reading.p_full,
        "source": reading.source,
        "model_horizon_min": reading.model_horizon_min,
    }


__all__ = [
    "REASON_BELOW_THRESHOLD",
    "REASON_COOLDOWN",
    "REASON_FORCED",
    "REASON_HORIZON_OUT_OF_RANGE",
    "REASON_LOW_CONFIDENCE",
    "REASON_LOW_PREDICTED_STOCK",
    "REASON_P_EMPTY",
    "REASON_STOCK_UNKNOWN",
    "SOURCE_GLOBAL_FALLBACK",
    "StockReading",
    "Thresholds",
    "TriggerResult",
    "evaluate",
]
