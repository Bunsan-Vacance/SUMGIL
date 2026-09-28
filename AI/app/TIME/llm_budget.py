"""LLM 세션 비용 가드(S15P21A104-203) — `guard.ToolGuard`의 LLM판.

**세션 단위 인스턴스다.** 모듈 전역 싱글턴으로 만들지 않는 이유는 `guard.ToolGuard`
docstring 첫 문단과 같다 — 예산은 "이 사용자의 이 루프가 LLM을 얼마나 썼나"를 재는 값이라,
인스턴스를 공유하면 먼저 온 사용자가 예산을 다 써서 뒤에 온 사용자가 아무것도 못 부르게 된다.
세션 시작 시 하나 만들고 끝나면 버린다.

로그에는 호출 수·입출력 토큰 수·소요 ms만 남긴다. **프롬프트 본문·인자 값은 남기지 않는다**
(`TOOL_CONTRACT.md` 5.2절과 같은 이유 — 프롬프트에는 사용자의 이동 경로가 그대로 들어가므로
남기기 시작하면 로그가 사실상 위치 추적 기록이 된다).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.TIME.llm import LlmError, LlmErrorCode, LlmResult

DEFAULT_MAX_CALLS_PER_SESSION = 3
DEFAULT_MAX_TOKENS_PER_SESSION = 8000
"""**잠정값, 근거 없음.** 실제 프롬프트 크기·게이트웨이 단가를 보지 못한 채 우선 막아둔 값이다
(`app/core/config.py`의 같은 이름 주석과 동일한 처지)."""


@dataclass(slots=True)
class LlmBudget:
    """세션 하나의 LLM 호출·토큰 예산."""

    max_calls: int = DEFAULT_MAX_CALLS_PER_SESSION
    max_total_tokens: int = DEFAULT_MAX_TOKENS_PER_SESSION

    calls: int = field(default=0, init=False)
    total_tokens: int = field(default=0, init=False)

    def check(self) -> LlmError | None:
        """호출 직전 확인. 통과면 None, 넘었으면 그대로 돌려줘도 되는 `LlmError`.

        **상태를 바꾸지 않는다.** 예산 소비는 `record()`가 한다(`guard.ToolGuard.check`와
        같은 이유 — 여기서 미리 깎으면 호출이 실패해 `record`가 안 불렸을 때 쓰지도 않은
        예산이 사라진다).
        """
        if self.calls >= self.max_calls:
            return LlmError(
                code=LlmErrorCode.BUDGET_EXCEEDED,
                detail=f"이 세션의 LLM 호출 한도 {self.max_calls}회를 모두 썼다.",
                retryable=False,
            )
        if self.total_tokens >= self.max_total_tokens:
            return LlmError(
                code=LlmErrorCode.BUDGET_EXCEEDED,
                detail=f"이 세션의 LLM 토큰 한도 {self.max_total_tokens}를 모두 썼다.",
                retryable=False,
            )
        return None

    def record(self, result: LlmResult) -> None:
        """성공한 호출 하나를 예산에서 깎는다.

        토큰 수를 모르면(`None`) 0으로 친다 — "안 세어졌다"와 "0개 썼다"를 구분하지는
        못하지만, 예산을 실제보다 더 깎아 정상 호출까지 막는 쪽보다는 안전하다.
        """
        self.calls += 1
        self.total_tokens += (result.input_tokens or 0) + (result.output_tokens or 0)


__all__ = ["DEFAULT_MAX_CALLS_PER_SESSION", "DEFAULT_MAX_TOKENS_PER_SESSION", "LlmBudget"]
