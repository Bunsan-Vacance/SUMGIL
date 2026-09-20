"""도구 호출 가드(S15P21A104-202) — 호출 예산·레이트리밋·호출 로그.

**예산 초과는 예외가 아니라 값이다.** `schemas.ToolError`와 같은 이유로, 가드가 예외를 던지면
에이전트 루프가 통째로 죽고 LLM은 왜 막혔는지 모른 채 끝난다. `BUDGET_EXCEEDED`를 정상
반환값으로 주면 에이전트가 "이제 그만 부르고 답하라"를 읽을 수 있다 — 가드의 목적은 호출을
막는 것 자체가 아니라 **루프를 못 벗어나는 에이전트를 도구 계층이 끊어주는 것**이다.

기본 예산의 근거(계획 4절):

| 항목 | 기본값 | 근거 |
| --- | --- | --- |
| 세션당 총 호출 | 20 | 실제 계획은 replan 5 + arrivals 1이라 3배 여유 |
| `replan_route` | 5 | 하차 후보역 상한이 5 |
| 그 밖의 도구 | 10 | |
| 초당 호출 | 10 | BE 부하 보호 |

LLM 토큰 비용 가드는 이번 범위가 아니다(모델·단가 미정, 203에서 붙인다).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TypeVar

from app.TIME.registry import REPLAN_ROUTE
from app.TIME.schemas import ToolError, ToolErrorCode

T = TypeVar("T")

DEFAULT_TOTAL_BUDGET = 20
DEFAULT_PER_TOOL_BUDGET = 10
DEFAULT_TOOL_BUDGETS: Mapping[str, int] = MappingProxyType({REPLAN_ROUTE: 5})
"""도구별 예외 예산. 모듈 전역이라 인스턴스가 실수로 고치지 못하게 읽기 전용으로 둔다."""

DEFAULT_MAX_PER_SECOND = 10
RATE_WINDOW_SEC = 1.0

RESULT_OK = "ok"
"""로그의 결과 종류. 실패는 `ToolErrorCode` 값을 그대로 쓴다."""

RESULT_EXCEPTION = "exception"
"""도구가 계약을 어기고 예외를 던진 경우. 예산은 그래도 깎는다 — 안 깎으면 무한 재시도가 된다."""


def arg_keys_of(args: Mapping[str, object] | None) -> tuple[str, ...]:
    """인자 매핑에서 **키만** 뽑는다.

    값은 이 함수에서 버려지고 그 뒤 어디에도 남지 않는다. 도구 인자에는 좌표·역 ID·목적지처럼
    사용자의 이동 경로가 그대로 들어 있어서, 디버깅 편의로 값을 남기기 시작하면 메모리 로그가
    사실상 위치 추적 기록이 된다. 어떤 인자로 불렀는지(= 호출 모양)는 키만으로 충분히 드러난다.
    """
    return tuple(args) if args else ()


@dataclass(frozen=True, slots=True)
class ToolCallLog:
    """호출 기록 한 줄. LLM에 들어가지 않는 내부 telemetry라 pydantic 대신 dataclass를 쓴다."""

    tool: str
    elapsed_ms: float
    result_code: str
    """`ok` 또는 `ToolErrorCode` 값, 혹은 `exception`."""

    arg_keys: tuple[str, ...]
    """인자의 **키 목록**. 값은 담지 않는다 — `arg_keys_of` 주석 참고."""

    at: float
    """호출 시작 시각(주입된 시계 기준). 벽시계가 아니라 단조 시계 값이라 시각 표시용이 아니다."""

    blocked: bool = False
    """가드가 막아서 도구가 아예 실행되지 않은 호출. 예산을 깎지 않는다."""


@dataclass(slots=True)
class ToolStats:
    """도구 하나의 누적 집계."""

    calls: int = 0
    """실제로 실행된 호출 수(= 예산을 깎은 수). blocked는 포함하지 않는다."""

    ok: int = 0
    failed: int = 0
    blocked: int = 0
    total_ms: float = 0.0


class ToolGuard:
    """한 세션(사용자 요청 하나의 에이전트 루프)의 도구 호출 예산·레이트·로그.

    **모듈 전역 싱글턴으로 만들지 않는다.** 예산은 "이 사용자의 이 루프가 얼마나 헤맸나"를 재는
    값이라, 인스턴스를 공유하면 먼저 온 사용자가 예산을 다 써서 뒤에 온 사용자가 아무것도 못
    부르게 된다. 호출 로그도 마찬가지로 세션 밖으로 섞이면 안 된다. 세션 시작 시 하나 만들고
    끝나면 버린다.

    시계는 생성자로 주입받는다(`clock`, 기본 `time.monotonic`). 레이트리밋을 `time.sleep`으로
    테스트하면 테스트가 느려지고 CI에서 불안정해져서, 시간을 앞으로 돌릴 수 있게 열어뒀다.
    단조 시계를 쓰는 이유는 NTP 보정으로 벽시계가 뒤로 가면 창(window)이 음수가 되기 때문이다.
    """

    def __init__(
        self,
        *,
        total_budget: int = DEFAULT_TOTAL_BUDGET,
        per_tool_budget: int = DEFAULT_PER_TOOL_BUDGET,
        tool_budgets: Mapping[str, int] | None = None,
        max_per_second: int = DEFAULT_MAX_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.total_budget = total_budget
        self.per_tool_budget = per_tool_budget
        self.tool_budgets: dict[str, int] = dict(
            DEFAULT_TOOL_BUDGETS if tool_budgets is None else tool_budgets
        )
        self.max_per_second = max_per_second
        self._clock = clock
        self._counts: dict[str, int] = {}
        self._stats: dict[str, ToolStats] = {}
        self._log: list[ToolCallLog] = []
        self._recent: deque[float] = deque()
        """레이트 창 안의 실행 시각. 로그를 매번 훑지 않으려고 따로 둔다(막힌 호출은 안 넣는다)."""

    # ── 조회 ──

    @property
    def total_calls(self) -> int:
        """실행된 호출 수. 막힌 호출은 세지 않는다."""
        return sum(self._counts.values())

    def budget_for(self, name: str) -> int:
        """도구별 한도. 도구 이름 자체가 유효한지는 검사하지 않는다 —
        그 판정은 어댑터(`INVALID_INPUT`) 몫이고, 모르는 이름도 총 예산에 묶여 있어 무한히
        불릴 수 없다."""
        return self.tool_budgets.get(name, self.per_tool_budget)

    def logs(self) -> tuple[ToolCallLog, ...]:
        """호출 로그 전체. 메모리에만 있고 파일·외부 전송은 이번 범위가 아니다.
        호출자가 내부 리스트를 건드리지 못하도록 복사본을 준다."""
        return tuple(self._log)

    def stats(self) -> dict[str, ToolStats]:
        """도구별 집계 사본. 한 번도 안 불린 도구는 키가 없다."""
        return {name: replace(stat) for name, stat in self._stats.items()}

    # ── 판정·기록 ──

    def check(self, name: str) -> ToolError | None:
        """호출 직전 확인. 통과면 None, 막히면 그대로 반환해도 되는 `ToolError`.

        **상태를 바꾸지 않는다.** 예산 소비는 `record()`가 한다 — 여기서 미리 깎으면 도구가
        예외로 튀거나 호출자가 중간에 빠져나갔을 때 쓰지도 않은 예산이 사라진다. 대신 `check`만
        하고 `record`를 빠뜨리면 예산이 영원히 안 깎이므로, 되도록 `run()`을 쓴다.
        """
        if self.total_calls >= self.total_budget:
            return ToolError.budget_exceeded(
                f"이 세션의 도구 호출 한도 {self.total_budget}회를 모두 썼다. "
                "더 부르지 말고 지금까지 모은 결과로 답할 것."
            )
        limit = self.budget_for(name)
        if self._counts.get(name, 0) >= limit:
            return ToolError.budget_exceeded(
                f"'{name}' 호출 한도 {limit}회를 모두 썼다. "
                "이 도구는 더 부를 수 없으니 이미 받은 결과로 판단할 것."
            )
        if self._rate_used() >= self.max_per_second:
            return ToolError.rate_limited(
                f"초당 호출 한도 {self.max_per_second}회를 넘었다. 잠시 뒤 다시 부를 것."
            )
        return None

    def record(
        self,
        name: str,
        *,
        elapsed_ms: float,
        result_code: str,
        arg_keys: Iterable[str] = (),
        at: float | None = None,
    ) -> ToolCallLog:
        """실행된 호출 하나를 예산에서 깎고 로그에 남긴다.

        실패한 호출도 예산을 깎는다 — 상류가 죽었을 때 같은 도구를 계속 재시도하는 것이
        정확히 이 가드가 끊어야 할 루프이기 때문이다.

        `at`은 호출 **시작** 시각이다. 레이트 창은 시작 기준으로 세야 오래 걸린 호출 하나가
        창을 통째로 밀어내지 않는다.
        """
        started = self._clock() if at is None else at
        entry = ToolCallLog(
            tool=name,
            elapsed_ms=elapsed_ms,
            result_code=result_code,
            # 값이 섞여 들어와도 키 자리에만 남도록 문자열로 고정한다.
            arg_keys=tuple(str(key) for key in arg_keys),
            at=started,
        )
        self._log.append(entry)
        self._counts[name] = self._counts.get(name, 0) + 1
        self._recent.append(started)
        stat = self._stat_for(name)
        stat.calls += 1
        stat.total_ms += elapsed_ms
        if result_code == RESULT_OK:
            stat.ok += 1
        else:
            stat.failed += 1
        return entry

    def run(
        self,
        name: str,
        fn: Callable[[], T],
        args: Mapping[str, object] | None = None,
    ) -> T | ToolError:
        """`check` → 실행 → `record`를 한 덩어리로 묶은 권장 경로.

        호출자가 `record`를 빠뜨려 예산이 안 깎이는 실수를 구조적으로 막는다. `fn`은 인자 없이
        불리므로 어댑터는 `lambda`/`functools.partial`로 감싼다. `args`는 **키만** 뽑아 로그에
        남기고 값은 버린다 — 호출자가 값을 따로 넘길 자리를 아예 두지 않았다.

        막히면 도구를 부르지 않고 `ToolError`를 그대로 돌려준다. 막힌 호출도 로그에는 남긴다
        (에이전트가 어디서 벽에 부딪혔는지가 203 루프 디버깅의 주 단서다).
        """
        keys = arg_keys_of(args)
        blocked = self.check(name)
        if blocked is not None:
            self._log.append(
                ToolCallLog(
                    tool=name,
                    elapsed_ms=0.0,
                    result_code=blocked.error.value,
                    arg_keys=keys,
                    at=self._clock(),
                    blocked=True,
                )
            )
            self._stat_for(name).blocked += 1
            return blocked

        started = self._clock()
        try:
            result = fn()
        except Exception:
            # 도구는 예외를 던지지 않기로 했지만(schemas.py), 어겼을 때 예산이 안 깎이면
            # 같은 호출이 무한히 반복된다. 기록만 하고 예외는 그대로 올려보낸다.
            self.record(
                name,
                elapsed_ms=self._elapsed_ms(started),
                result_code=RESULT_EXCEPTION,
                arg_keys=keys,
                at=started,
            )
            raise
        self.record(
            name,
            elapsed_ms=self._elapsed_ms(started),
            result_code=result_code_of(result),
            arg_keys=keys,
            at=started,
        )
        return result

    # ── 내부 ──

    def _elapsed_ms(self, started: float) -> float:
        return (self._clock() - started) * 1000.0

    def _rate_used(self) -> int:
        """레이트 창 안의 실행 수. 지나간 시각은 여기서 버린다."""
        cutoff = self._clock() - RATE_WINDOW_SEC
        while self._recent and self._recent[0] <= cutoff:
            self._recent.popleft()
        return len(self._recent)

    def _stat_for(self, name: str) -> ToolStats:
        stat = self._stats.get(name)
        if stat is None:
            stat = ToolStats()
            self._stats[name] = stat
        return stat


def result_code_of(result: object) -> str:
    """도구 반환값에서 로그에 남길 결과 종류를 뽑는다.

    `ToolError` 객체와 직렬화된 dict를 모두 받는다 — 로컬 어댑터는 객체를, HTTP 어댑터는
    dict를 돌려줄 수 있어서 한쪽만 보면 실패가 전부 `ok`로 집계된다.
    """
    if isinstance(result, ToolError):
        return result.error.value
    if isinstance(result, Mapping):
        code = result.get("error")
        if code in set(ToolErrorCode):
            return str(code)
    return RESULT_OK
