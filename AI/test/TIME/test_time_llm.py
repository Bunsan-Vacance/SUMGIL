"""LLM 게이트웨이 클라이언트 검증(S15P21A104-203-A).

`adapters.py`의 HTTP 어댑터 테스트와 같은 방식 — `requests.request`를 monkeypatch하고 실제
소켓은 열지 않는다. 지키려는 것도 같다: **어떤 실패든 예외로 새지 않고 `LlmError`라는 값으로
돌아오는지**, 그리고 **설정이 없어도 생성·import 자체는 성공하는지**(호출 시점에만 실패).
"""

from __future__ import annotations

import json

import pytest
import requests

from app.TIME.llm import (
    DEFAULT_TIMEOUT_SEC,
    HttpLlmClient,
    LlmError,
    LlmErrorCode,
    LlmResult,
    settings_client,
)
from app.TIME.llm_budget import LlmBudget

BASE_URL = "https://gms.example.com/v1"
API_KEY = "test-key"
MODEL = "test-model"


# ── 가짜 HTTP ──


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        if text is not None:
            self.text = text
        elif payload is None:
            self.text = ""
        else:
            self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("본문이 JSON이 아니다")
        return self._payload


def _patch_requests(monkeypatch: pytest.MonkeyPatch, handler) -> list[dict]:
    captured: list[dict] = []

    def fake_request(**kwargs):
        captured.append(kwargs)
        return handler(**kwargs)

    monkeypatch.setattr(requests, "request", fake_request)
    return captured


def _respond(response: _FakeResponse):
    return lambda **_: response


def _raise(exc: Exception):
    def handler(**_):
        raise exc

    return handler


def _chat_payload(content: str, *, usage: dict | None = None, model: str = MODEL) -> dict:
    payload: dict = {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def _client(**overrides) -> HttpLlmClient:
    kwargs = {"base_url": BASE_URL, "api_key": API_KEY, "model": MODEL}
    kwargs.update(overrides)
    return HttpLlmClient(**kwargs)


# ── 설정 없어도 생성·import는 성공 ──


def test_설정이_없어도_생성은_성공한다() -> None:
    client = HttpLlmClient(base_url=None, api_key=None, model=None)
    assert client.base_url == ""
    assert client.timeout_sec == DEFAULT_TIMEOUT_SEC


def test_모듈_임포트는_환경변수_없이도_성공한다() -> None:
    import importlib

    module = importlib.import_module("app.TIME.llm")
    assert hasattr(module, "HttpLlmClient")


# ── 설정 누락 ──


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": None},
        {"api_key": None},
        {"model": None},
    ],
)
def test_설정_하나라도_없으면_CONFIG_MISSING이다(
    monkeypatch: pytest.MonkeyPatch, overrides: dict
) -> None:
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, _chat_payload("{}"))))
    client = _client(**overrides)

    result = client.complete(system="s", user="u")

    assert isinstance(result, LlmError)
    assert result.code is LlmErrorCode.CONFIG_MISSING
    assert result.retryable is False
    assert captured == []  # 설정이 없으면 요청 자체를 보내지 않는다


# ── 정상 ──


def test_정상_응답을_LlmResult로_돌려준다(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _chat_payload(
        '{"chosen_index": 0, "reason": "테스트"}',
        usage={"prompt_tokens": 120, "completion_tokens": 40},
    )
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, payload)))

    result = _client().complete(system="시스템", user="사용자")

    assert isinstance(result, LlmResult)
    assert result.text == '{"chosen_index": 0, "reason": "테스트"}'
    assert result.input_tokens == 120
    assert result.output_tokens == 40
    assert result.model == MODEL
    assert result.latency_ms >= 0.0

    # 요청이 OpenAI 호환 chat/completions 모양으로 나갔는지 — _build_request 계약.
    (request,) = captured
    assert request["method"] == "POST"
    assert request["url"] == f"{BASE_URL}/chat/completions"
    assert request["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert request["json"]["messages"] == [
        {"role": "system", "content": "시스템"},
        {"role": "user", "content": "사용자"},
    ]


def test_usage가_없으면_토큰_수는_0이_아니라_None이다(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _chat_payload("괜찮은 응답")  # usage 키 자체가 없다
    _patch_requests(monkeypatch, _respond(_FakeResponse(200, payload)))

    result = _client().complete(system="s", user="u")

    assert isinstance(result, LlmResult)
    assert result.input_tokens is None
    assert result.output_tokens is None


# ── 실패 ──


def test_타임아웃은_TIMEOUT이고_재시도_가치가_있다(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_requests(monkeypatch, _raise(requests.Timeout("게이트웨이 응답 없음")))

    result = _client().complete(system="s", user="u")

    assert isinstance(result, LlmError)
    assert result.code is LlmErrorCode.TIMEOUT
    assert result.retryable is True


def test_연결_실패는_UPSTREAM_ERROR다(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_requests(monkeypatch, _raise(requests.ConnectionError("연결 거부")))

    result = _client().complete(system="s", user="u")

    assert isinstance(result, LlmError)
    assert result.code is LlmErrorCode.UPSTREAM_ERROR
    assert result.retryable is True


def test_5xx는_UPSTREAM_ERROR고_재시도_가치가_있다(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_requests(monkeypatch, _respond(_FakeResponse(503, text="Service Unavailable")))

    result = _client().complete(system="s", user="u")

    assert isinstance(result, LlmError)
    assert result.code is LlmErrorCode.UPSTREAM_ERROR
    assert result.retryable is True


def test_4xx는_UPSTREAM_ERROR지만_재시도_가치가_없다(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_requests(monkeypatch, _respond(_FakeResponse(401, text="Unauthorized")))

    result = _client().complete(system="s", user="u")

    assert isinstance(result, LlmError)
    assert result.code is LlmErrorCode.UPSTREAM_ERROR
    assert result.retryable is False


def test_JSON이_깨지면_BAD_RESPONSE다(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_requests(
        monkeypatch, _respond(_FakeResponse(200, payload=None, text="<html>오류</html>"))
    )

    result = _client().complete(system="s", user="u")

    assert isinstance(result, LlmError)
    assert result.code is LlmErrorCode.BAD_RESPONSE
    assert result.retryable is False


def test_choices가_없으면_BAD_RESPONSE다(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"unexpected": "shape"})))

    result = _client().complete(system="s", user="u")

    assert isinstance(result, LlmError)
    assert result.code is LlmErrorCode.BAD_RESPONSE


# ── json_schema 인자 ──


def test_json_schema를_주면_response_format에_실린다(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, _chat_payload("{}"))))
    schema = {"type": "object", "properties": {"chosen_index": {"type": "integer"}}}

    _client().complete(system="s", user="u", json_schema=schema)

    (request,) = captured
    assert request["json"]["response_format"]["type"] == "json_schema"
    assert request["json"]["response_format"]["json_schema"]["schema"] == schema


# ── settings_client 팩토리 ──


def test_settings_client는_Settings_필드에서_읽는다() -> None:
    class FakeSettings:
        time_llm_base_url = BASE_URL
        time_llm_api_key = API_KEY
        time_llm_model = MODEL
        time_llm_timeout_sec = 9.0

    client = settings_client(FakeSettings())

    assert client.base_url == BASE_URL
    assert client.api_key == API_KEY
    assert client.model == MODEL
    assert client.timeout_sec == 9.0


def test_settings_client는_값이_없어도_생성된다() -> None:
    class EmptySettings:
        pass

    client = settings_client(EmptySettings())

    assert client.base_url == ""
    result = client.complete(system="s", user="u")
    assert isinstance(result, LlmError)
    assert result.code is LlmErrorCode.CONFIG_MISSING


# ── LlmBudget ──


def _result(input_tokens: int | None = 10, output_tokens: int | None = 10) -> LlmResult:
    return LlmResult(
        text="{}",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=1.0,
        model=MODEL,
    )


def test_예산_안에서는_통과한다() -> None:
    budget = LlmBudget(max_calls=3, max_total_tokens=1000)
    assert budget.check() is None

    budget.record(_result())
    assert budget.check() is None
    assert budget.calls == 1
    assert budget.total_tokens == 20


def test_호출_수를_넘기면_BUDGET_EXCEEDED다() -> None:
    budget = LlmBudget(max_calls=2, max_total_tokens=10_000)
    budget.record(_result())
    budget.record(_result())

    error = budget.check()

    assert isinstance(error, LlmError)
    assert error.code is LlmErrorCode.BUDGET_EXCEEDED
    assert error.retryable is False


def test_토큰_한도를_넘기면_BUDGET_EXCEEDED다() -> None:
    budget = LlmBudget(max_calls=100, max_total_tokens=50)
    budget.record(_result(input_tokens=30, output_tokens=30))  # 합 60 > 50

    error = budget.check()

    assert isinstance(error, LlmError)
    assert error.code is LlmErrorCode.BUDGET_EXCEEDED


def test_토큰_수를_모르면_0으로_친다() -> None:
    budget = LlmBudget(max_calls=10, max_total_tokens=10)
    budget.record(_result(input_tokens=None, output_tokens=None))

    assert budget.total_tokens == 0
    assert budget.check() is None


def test_check는_상태를_바꾸지_않는다() -> None:
    budget = LlmBudget(max_calls=1, max_total_tokens=1000)
    budget.check()
    budget.check()

    assert budget.calls == 0  # record를 안 불렀으니 여전히 0이어야 한다
