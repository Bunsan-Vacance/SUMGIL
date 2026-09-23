"""LLM 게이트웨이 클라이언트(S15P21A104-203) — `AgentStrategy`가 부르는 유일한 외부 호출 지점.

어댑터(`adapters.py`)와 같은 규칙을 따른다: **예외를 던지지 않고 실패를 값으로 낸다.** 전략
(`strategy.AgentStrategy`) 안에서 예외가 올라오면 규칙 폴백으로 넘어갈 기회조차 없이 그 자리에서
루프가 죽는다 — `schemas.py` 첫 문단·`adapters.py` 첫 문단과 같은 이유다.

**게이트웨이(GMS) 형식은 OpenAI 호환으로 확인됐다**(2026-09-23 실호출 1회, `TOOL_CONTRACT.md`
6절 5번). `POST {base_url}/chat/completions`, `Authorization: Bearer <GMS_API_KEY>`, `messages`,
`response_format.json_schema(strict)`가 그대로 통하고, 출력 상한은 `max_completion_tokens`(정수 — `max_tokens`는 gpt-5 계열이 400으로 거부한다, 2026-09-23 확인. 값이
있을 때만 body에 실린다 — `Settings.time_llm_max_output_tokens` 참고)로 건다. 응답도
`choices[0].message.content`·`usage.prompt_tokens/completion_tokens`·`model`(예:
`gpt-5.4-mini-2026-03-17`) 구조다. base_url은 `https://gms.ssafy.io/gmsapi/api.openai.com/v1`,
모델은 `gpt-5.4-mini`(`.env`). 같은 게이트웨이의 Gemini 경로
(`generativelanguage.googleapis.com/v1beta/...:generateContent`, `x-goog-api-key`)는 형식이
달라 이 클라이언트로는 못 쓴다 — 바꿀 일이 생기면 `_build_request()`·`_parse_response()` 두
함수만 고치면 되도록 요청 조립과 응답 파싱을 여기 격리해뒀다. 그 밖의 코드(`complete()`
호출부·`AgentStrategy`)는 `LlmResult`/`LlmError`만 보고 게이트웨이가 어떤 모양인지 모른다.

`max_completion_tokens`에 잘려 응답이 중간에 끊기면 `LlmResult.text`는 깨진 JSON 문자열을 그대로 담고,
이 클라이언트는 그것도 성공(`LlmResult`)으로 돌려준다 — 잘림 자체는 HTTP 오류가 아니기
때문이다. 이후 `strategy._parse_decision`이 `json.loads` 실패로 `None`을 돌려주고
`AgentStrategy.decide`가 `RejectReason.BAD_JSON`으로 규칙 폴백에 넘어간다 — 별도 처리 없이
기존 파싱 실패 경로가 그대로 잡아준다.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import requests

DEFAULT_TIMEOUT_SEC = 4.0


class LlmErrorCode(StrEnum):
    """LLM 호출 실패 분류. `schemas.ToolErrorCode`와 같은 이유로 값 하나로 뭉개지 않는다 —
    값은 로그·204 평가 하네스가 읽으므로 의미가 자명해야 한다."""

    CONFIG_MISSING = "CONFIG_MISSING"
    """API 키·게이트웨이 주소·모델명 중 하나라도 없다. 재시도로 해결되지 않는다."""

    TIMEOUT = "TIMEOUT"
    """게이트웨이가 제한 시간 안에 응답하지 않았다. 다음 폴링에서 다시 될 수 있다."""

    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    """게이트웨이가 4xx/5xx를 돌려줬거나 연결 자체가 안 됐다. GMS 형식이 미확정이라
    상태코드별로 잘게 나누지 않고 한 값으로 묶는다."""

    BAD_RESPONSE = "BAD_RESPONSE"
    """응답은 왔는데 JSON이 깨졌거나 기대한 필드(choices[0].message.content)가 없다."""

    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    """이 세션의 LLM 호출·토큰 예산을 다 썼다. `llm_budget.LlmBudget.check()`가 낸다."""


@dataclass(frozen=True)
class LlmResult:
    """LLM 호출 성공."""

    text: str
    """모델이 낸 원문. JSON 파싱·검증은 호출자(`strategy.AgentStrategy`)의 몫이다 — 이
    클라이언트는 게이트웨이 응답에서 본문만 꺼낼 뿐 그 내용의 의미를 모른다."""

    input_tokens: int | None
    output_tokens: int | None
    """게이트웨이 응답에 `usage`가 없으면 **0이 아니라 None**이다. "안 셌다"와 "0개 썼다"를
    섞으면 비용 가드가 잘못된 값으로 예산을 깎는다(`schemas.py`의 NOT_FOUND/UPSTREAM_UNAVAILABLE
    구분과 같은 태도)."""

    latency_ms: float
    model: str


@dataclass(frozen=True)
class LlmError:
    """LLM 호출 실패. 성공과 같은 자리에서 반환된다."""

    code: LlmErrorCode
    detail: str
    retryable: bool


LlmOutcome = LlmResult | LlmError


class LlmClient(Protocol):
    """LLM 게이트웨이를 부르는 객체. 구현체는 예외 대신 `LlmError`를 돌려준다."""

    def complete(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LlmOutcome: ...


class HttpLlmClient:
    """OpenAI 호환 게이트웨이를 부른다.

    `base_url`·`api_key`·`model` 중 하나라도 없어도 **생성·import는 성공한다** — 이유는
    `adapters.HttpAdapter` docstring(4.2절)과 같다. 게이트웨이 주소가 아직 확정되지 않았다고
    전략 계층 전체가 죽으면 LLM 없이도 동작해야 할 규칙 폴백까지 같이 막힐 이유가 없다.
    미설정은 `complete()` 호출 시점에만 `CONFIG_MISSING`으로 드러난다.
    """

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        max_output_tokens: int | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_output_tokens = max_output_tokens

    def complete(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LlmOutcome:
        missing = self._missing_config()
        if missing:
            return LlmError(
                code=LlmErrorCode.CONFIG_MISSING,
                detail=f"LLM 게이트웨이 설정이 없다: {', '.join(missing)}",
                retryable=False,
            )

        request = _build_request(
            self.base_url,
            self.api_key,
            self.model,
            system,
            user,
            json_schema=json_schema,
            max_output_tokens=self.max_output_tokens,
        )

        started = time.monotonic()
        try:
            response = requests.request(timeout=self.timeout_sec, **request)
        except requests.Timeout as exc:
            return LlmError(
                code=LlmErrorCode.TIMEOUT,
                detail=f"게이트웨이 응답 시간 초과({self.timeout_sec}초): {exc}",
                retryable=True,
            )
        except requests.RequestException as exc:
            # 연결 실패를 포함한 그 밖의 요청 예외 — GMS 형식이 미확정이라 상태코드 오류와
            # 같은 값(UPSTREAM_ERROR)으로 묶는다(모듈 docstring).
            return LlmError(
                code=LlmErrorCode.UPSTREAM_ERROR,
                detail=f"게이트웨이 호출 실패({type(exc).__name__}): {exc}",
                retryable=True,
            )
        elapsed_ms = (time.monotonic() - started) * 1000.0

        if response.status_code >= 400:
            # 5xx는 게이트웨이 쪽 일시 장애일 수 있어 재시도 가치가 있고, 4xx는 요청 자체가
            # 잘못됐을 가능성이 커 재시도해도 같은 결과다.
            return LlmError(
                code=LlmErrorCode.UPSTREAM_ERROR,
                detail=f"게이트웨이 응답 {response.status_code}: {_snippet(response)}",
                retryable=response.status_code >= 500,
            )

        try:
            payload = response.json()
        except ValueError:
            return LlmError(
                code=LlmErrorCode.BAD_RESPONSE,
                detail="게이트웨이 응답이 JSON이 아니다",
                retryable=False,
            )
        except Exception as exc:  # noqa: BLE001 - adapters.py와 같은 이유의 마지막 그물
            return LlmError(
                code=LlmErrorCode.BAD_RESPONSE,
                detail=f"게이트웨이 응답 해석 실패({type(exc).__name__}): {exc}",
                retryable=False,
            )

        return _parse_response(payload, model=self.model, latency_ms=elapsed_ms)

    def _missing_config(self) -> list[str]:
        missing: list[str] = []
        if not self.base_url:
            missing.append("base_url")
        if not self.api_key:
            missing.append("api_key")
        if not self.model:
            missing.append("model")
        return missing


def _build_request(
    base_url: str,
    api_key: str | None,
    model: str | None,
    system: str,
    user: str,
    *,
    json_schema: dict[str, Any] | None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """`requests.request()` 인자를 만든다. **GMS의 실제 요청 형식이 확정되면 이 함수만
    고치면 된다** — 호출부(`HttpLlmClient.complete`)는 이 함수가 낸 매핑을 그대로
    `requests.request(**request)`에 펼쳐 쓸 뿐 내부를 모른다.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "agent_decision", "schema": json_schema, "strict": True},
        }
    else:
        body["response_format"] = {"type": "json_object"}
    if max_output_tokens is not None:
        body["max_completion_tokens"] = max_output_tokens

    return {
        "method": "POST",
        "url": f"{base_url}/chat/completions",
        "headers": {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        "json": body,
    }


def _parse_response(payload: Any, *, model: str | None, latency_ms: float) -> LlmOutcome:
    """OpenAI 호환 응답에서 본문·토큰 사용량을 꺼낸다. **GMS의 실제 응답 형식이 확정되면
    이 함수만 고치면 된다** — 호출부는 이 함수가 낸 `LlmResult`/`LlmError`만 본다.
    """
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return LlmError(
            code=LlmErrorCode.BAD_RESPONSE,
            detail=f"게이트웨이 응답에 choices[0].message.content가 없다: {payload!r}"[:300],
            retryable=False,
        )
    if not isinstance(text, str):
        return LlmError(
            code=LlmErrorCode.BAD_RESPONSE,
            detail=f"choices[0].message.content가 문자열이 아니다: {type(text).__name__}",
            retryable=False,
        )

    usage = payload.get("usage") if isinstance(payload, Mapping) else None
    input_tokens = (
        _as_token_count(usage.get("prompt_tokens")) if isinstance(usage, Mapping) else None
    )
    output_tokens = (
        _as_token_count(usage.get("completion_tokens")) if isinstance(usage, Mapping) else None
    )

    response_model = payload.get("model") if isinstance(payload, Mapping) else None
    return LlmResult(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        model=str(response_model or model or ""),
    )


def _as_token_count(value: Any) -> int | None:
    """usage 필드 하나를 정수로. 없거나 숫자가 아니면 0이 아니라 None(모듈 docstring 참고)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _snippet(response: Any, limit: int = 200) -> str:
    """오류 본문 앞부분. 로그·204 하네스에 들어가므로 길이를 자른다."""
    try:
        return str(response.text)[:limit]
    except Exception:  # noqa: BLE001 - adapters._snippet과 같은 이유. 본문을 못 읽는 것이
        # 오류 보고 자체를 막으면 안 된다.
        return "(본문 없음)"


def settings_client(settings: object) -> HttpLlmClient:
    """`Settings`에서 `HttpLlmClient`를 만드는 팩토리 하나. 값이 없어도 생성은 성공한다
    (`HttpLlmClient` docstring)."""
    return HttpLlmClient(
        base_url=getattr(settings, "time_llm_base_url", None),
        api_key=getattr(settings, "time_llm_api_key", None),
        model=getattr(settings, "time_llm_model", None),
        timeout_sec=getattr(settings, "time_llm_timeout_sec", DEFAULT_TIMEOUT_SEC),
        max_output_tokens=getattr(settings, "time_llm_max_output_tokens", None),
    )


__all__ = [
    "DEFAULT_TIMEOUT_SEC",
    "HttpLlmClient",
    "LlmClient",
    "LlmError",
    "LlmErrorCode",
    "LlmOutcome",
    "LlmResult",
    "settings_client",
]
