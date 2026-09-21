"""혼잡 급등 트리거 판정(S15P21A104-203).

**LLM을 쓰지 않는다.** 티켓 본문의 멘토 조언(9.14) — "가공 데이터에서는 통계·규칙이 AI보다 나을
수 있으니 억지로 넣지 말 것" — 을 그대로 따른다. 트리거는 이동 중 매 폴링마다 돌아가므로,
여기에 LLM을 넣으면 대부분의 호출이 "아무 일도 없음"을 확인하는 데 초당 비용을 쓴다.

**순수 함수다.** 혼잡도 조회는 호출자(`planner.py`)가 하고 여기는 읽은 값만 받는다. 그래야
① 테스트가 실제 parquet 없이 돌고, ② 규칙 기준선과 LLM 에이전트가 **완전히 같은 입력**으로
판정하는 것이 보장된다(`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번).

판정은 "지금 혼잡하다"가 아니라 **"도착할 시점에 지금보다 혼잡해진다"**이다. CROWD는 하루 1회
배치 산출물이라 실시간 값이 아니다 — 이 구분이 문구까지 바꾼다(`TOOL_CONTRACT.md` 3.3절).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

# `app/CROWD/SERVING_CONTRACT.md` 2절.
STATUS_OK = "ok"
STATUS_CALIBRATION_FALLBACK = "calibration_fallback"
STATUS_NO_DATA = "no_data"

USABLE_STATUSES = frozenset({STATUS_OK, STATUS_CALIBRATION_FALLBACK})
"""판정에 쓸 수 있는 상태. 나머지(no_lookup·segment_truncated·no_calibration)는 값이 null이라
**결측이지 혼잡이 아니다** — 상승으로도 하락으로도 세지 않는다."""


@dataclass(frozen=True)
class SlotReading:
    """한 역의 한 슬롯 혼잡도. `get_line_congestion` 응답 한 행에 대응한다."""

    time_slot_30min: str
    congestion_pct: float | None
    grade: int | None
    data_status: str

    @property
    def usable(self) -> bool:
        """상태가 쓸 수 있고 값도 둘 다 있는지.

        `data_status`가 ok여도 `grade`만 null인 셀이 있을 수 있어(배율표 결측) 값 유무를 따로
        본다 — 상태만 믿고 None을 빼면 그 자리에서 터진다.
        """
        return (
            self.data_status in USABLE_STATUSES
            and self.congestion_pct is not None
            and self.grade is not None
        )


@dataclass(frozen=True)
class StationReading:
    """앞쪽 역 하나에 대한 '지금'과 '도착할 때'의 짝. 호출자가 도착 슬롯을 계산해 채운다."""

    station_no: int
    station_name: str | None
    eta_minutes: int
    now: SlotReading
    on_arrival: SlotReading

    @property
    def comparable(self) -> bool:
        return self.now.usable and self.on_arrival.usable

    @property
    def grade_rise(self) -> int | None:
        if not self.comparable:
            return None
        return int(self.on_arrival.grade) - int(self.now.grade)  # type: ignore[arg-type]

    @property
    def pct_rise(self) -> float | None:
        if not self.comparable:
            return None
        return float(self.on_arrival.congestion_pct) - float(self.now.congestion_pct)  # type: ignore[arg-type]


@dataclass(frozen=True)
class TriggerThresholds:
    """`Settings`의 time_trigger_* 를 담는다. 전부 **잠정값**이다 — config.py 주석 참고."""

    grade_rise: int = 1
    pct_rise: float = 15.0
    min_run: int = 2
    cooldown_sec: float = 600.0

    @classmethod
    def from_settings(cls, settings: object) -> TriggerThresholds:
        return cls(
            grade_rise=getattr(settings, "time_trigger_grade_rise", 1),
            pct_rise=getattr(settings, "time_trigger_pct_rise", 15.0),
            min_run=getattr(settings, "time_trigger_min_run", 2),
            cooldown_sec=getattr(settings, "time_trigger_cooldown_sec", 600.0),
        )


# 트리거되지 않은 이유. 디버깅·평가(204)에서 "왜 안 떴나"를 세려면 불린 하나로는 부족하다.
SKIP_NO_DATA = "no_data"
SKIP_COOLDOWN = "cooldown"
SKIP_NO_READINGS = "no_readings"
SKIP_BELOW_THRESHOLD = "below_threshold"
SKIP_RUN_TOO_SHORT = "run_too_short"


@dataclass(frozen=True)
class TriggerDecision:
    """판정 결과. `facts`는 안내 문장(규칙 템플릿·LLM 모두)이 인용할 **사실만** 담는다."""

    fired: bool
    segment: tuple[StationReading, ...] = ()
    skip_reason: str | None = None
    facts: dict[str, object] = field(default_factory=dict)


def evaluate(
    readings: Sequence[StationReading],
    *,
    thresholds: TriggerThresholds | None = None,
    seconds_since_last_fire: float | None = None,
) -> TriggerDecision:
    """앞쪽 역들의 '지금 vs 도착할 때'를 보고 재안내를 띄울지 판정한다.

    `readings`는 **진행 순서**(가까운 역부터)여야 한다. 연속 구간 판정이 순서에 의존한다.

    `seconds_since_last_fire`가 쿨다운보다 작으면 조건을 보기 전에 접는다 — 같은 이동에서
    팝업이 반복해 뜨는 것을 막는다.
    """
    limits = thresholds or TriggerThresholds()

    if not readings:
        return TriggerDecision(fired=False, skip_reason=SKIP_NO_READINGS)

    # 배치 미실행은 "혼잡하지 않다"가 아니라 "판단할 근거가 없다"이다. 조건을 따지지 않고 접는다.
    if any(
        r.now.data_status == STATUS_NO_DATA or r.on_arrival.data_status == STATUS_NO_DATA
        for r in readings
    ):
        return TriggerDecision(fired=False, skip_reason=SKIP_NO_DATA)

    if seconds_since_last_fire is not None and seconds_since_last_fire < limits.cooldown_sec:
        return TriggerDecision(fired=False, skip_reason=SKIP_COOLDOWN)

    runs = _alerting_runs(readings, limits)
    if not runs:
        # 임계를 넘은 역이 하나도 없었는지, 넘었는데 연속이 짧았는지를 구분해 남긴다.
        any_alerting = any(_is_alerting(r, limits) for r in readings)
        reason = SKIP_RUN_TOO_SHORT if any_alerting else SKIP_BELOW_THRESHOLD
        return TriggerDecision(fired=False, skip_reason=reason)

    # 여러 구간이 잡히면 가장 이른 것을 쓴다 — 사용자가 먼저 마주치는 구간이다.
    segment = runs[0]
    return TriggerDecision(fired=True, segment=segment, facts=_facts(segment))


def _is_alerting(reading: StationReading, limits: TriggerThresholds) -> bool:
    """등급과 %p를 **둘 다** 넘어야 한다(AND). 이유는 config.py 주석 참고."""
    if not reading.comparable:
        return False
    grade_rise = reading.grade_rise
    pct_rise = reading.pct_rise
    assert grade_rise is not None and pct_rise is not None  # comparable이 보장한다
    return grade_rise >= limits.grade_rise and pct_rise >= limits.pct_rise


def _alerting_runs(
    readings: Sequence[StationReading], limits: TriggerThresholds
) -> list[tuple[StationReading, ...]]:
    """임계를 넘은 역이 연속으로 `min_run`개 이상인 구간들.

    **결측 역(`comparable`이 False)은 구간을 끊지 않고, 연속 수에도 넣지 않는다.**
    끊는 쪽으로 하면 배율표 결측 하나 때문에 실제 혼잡 구간을 통째로 놓친다. 넣는 쪽으로 하면
    값이 없는 역을 혼잡하다고 세는 것이라 값 안 지어내기 원칙에 어긋난다. 둘 다 아닌 "건너뛴다"가
    남는 선택이다 — 다만 결측이 길게 이어지면 멀리 떨어진 두 역이 한 구간으로 묶일 수 있어,
    실제 표를 확보하면 결측 허용 길이 상한을 둘지 다시 본다.
    """
    runs: list[tuple[StationReading, ...]] = []
    current: list[StationReading] = []
    for reading in readings:
        if not reading.comparable:
            continue  # 끊지도 세지도 않는다
        if _is_alerting(reading, limits):
            current.append(reading)
            continue
        if len(current) >= limits.min_run:
            runs.append(tuple(current))
        current = []
    if len(current) >= limits.min_run:
        runs.append(tuple(current))
    return runs


def _facts(segment: Sequence[StationReading]) -> dict[str, object]:
    """안내 문장이 인용할 사실. **여기 없는 숫자는 문장에 쓰지 않는다.**

    규칙 템플릿과 LLM이 같은 사실 집합을 보게 해서, 둘의 차이가 '표현'에서만 나오고 '근거'에서는
    나오지 않도록 한다(7절 비교의 동등 조건).
    """
    first = segment[0]
    worst = max(segment, key=lambda r: r.pct_rise or 0.0)
    return {
        "station_count": len(segment),
        "first_station_no": first.station_no,
        "first_station_name": first.station_name,
        "first_eta_minutes": first.eta_minutes,
        "worst_station_no": worst.station_no,
        "worst_station_name": worst.station_name,
        "worst_eta_minutes": worst.eta_minutes,
        "worst_grade_from": worst.now.grade,
        "worst_grade_to": worst.on_arrival.grade,
        "worst_pct_from": worst.now.congestion_pct,
        "worst_pct_to": worst.on_arrival.congestion_pct,
        "arrival_slot": worst.on_arrival.time_slot_30min,
        # 공휴일에 일요일 배율을 빌려 쓴 셀이 섞였는지. 섞였으면 안내 문장이 그 사실을 밝혀야 한다.
        "calibration_fallback_used": any(
            r.now.data_status == STATUS_CALIBRATION_FALLBACK
            or r.on_arrival.data_status == STATUS_CALIBRATION_FALLBACK
            for r in segment
        ),
        # 예측이지 실측이 아니라는 것을 문장 생성 쪽이 잊지 않도록 사실로 박아둔다.
        "is_prediction": True,
    }
