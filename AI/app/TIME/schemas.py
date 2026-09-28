"""에이전트 도구 계층의 공통 타입(S15P21A104-202).

도구는 **예외를 던지지 않는다.** 실패도 `ToolError`라는 정상 반환값으로 낸다 — 에이전트 루프
한가운데서 예외가 올라오면 루프 전체가 죽고, LLM은 무슨 일이 있었는지 알 수 없다. 오류를 값으로
주면 에이전트가 "이 도구는 지금 못 쓴다"를 읽고 다른 경로를 택할 수 있다.

`ToolErrorCode`는 **"모른다"와 "없다"를 구분한다.** 이 프로젝트의 값 안 지어내기 원칙
(`Docs/Service Design/데이터-검증-리포트.md` 원칙 8가지)을 도구 계층에서 지키는 방식이다 —
데이터가 없는 것(`NOT_FOUND`)과 물어볼 수 없었던 것(`UPSTREAM_UNAVAILABLE`)을 같은 값으로
뭉개면 에이전트가 없는 것을 있다고 말하게 된다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ToolErrorCode(StrEnum):
    """도구 실패 분류. 값은 그대로 LLM 입력에 들어가므로 의미가 자명해야 한다."""

    INVALID_INPUT = "INVALID_INPUT"
    """인자가 스키마에 맞지 않는다. 같은 인자로 다시 불러도 같은 결과."""

    NOT_FOUND = "NOT_FOUND"
    """물어본 대상이 없다 — 없다는 사실 자체가 확인된 상태. 배치 미실행 표, 없는 역."""

    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    """물어보지 못했다 — 있는지 없는지 모르는 상태. BE 미기동·타임아웃·모델 아티팩트 장애."""

    RATE_LIMITED = "RATE_LIMITED"
    """호출이 너무 잦다. 잠시 뒤 재시도 가능."""

    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    """이 세션의 도구 호출 예산을 다 썼다. 재시도해도 소용없다 — 루프를 끊으라는 신호."""


class ToolError(BaseModel):
    """도구 실패. 성공 응답과 같은 자리에서 반환된다."""

    error: ToolErrorCode
    detail: str = Field(description="사람이 읽는 설명. 그대로 LLM 입력에 들어간다")
    retryable: bool = Field(description="같은 인자로 재시도할 가치가 있는지")

    @classmethod
    def invalid_input(cls, detail: str) -> ToolError:
        return cls(error=ToolErrorCode.INVALID_INPUT, detail=detail, retryable=False)

    @classmethod
    def not_found(cls, detail: str) -> ToolError:
        return cls(error=ToolErrorCode.NOT_FOUND, detail=detail, retryable=False)

    @classmethod
    def upstream_unavailable(cls, detail: str) -> ToolError:
        return cls(error=ToolErrorCode.UPSTREAM_UNAVAILABLE, detail=detail, retryable=True)

    @classmethod
    def rate_limited(cls, detail: str) -> ToolError:
        return cls(error=ToolErrorCode.RATE_LIMITED, detail=detail, retryable=True)

    @classmethod
    def budget_exceeded(cls, detail: str) -> ToolError:
        return cls(error=ToolErrorCode.BUDGET_EXCEEDED, detail=detail, retryable=False)


def is_error(result: object) -> bool:
    """도구 반환값이 실패인지. 어댑터·가드·에이전트가 같은 판정을 쓰도록 한곳에 둔다."""
    return isinstance(result, ToolError) or (
        isinstance(result, dict) and result.get("error") in set(ToolErrorCode)
    )
