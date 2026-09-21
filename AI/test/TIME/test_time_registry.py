"""도구 레지스트리 검증(S15P21A104-202).

스키마의 `description`은 LLM이 읽는 유일한 설명이라, 여기서 검증하는 건 "필드가 있는지"가 아니라
**결측 상태의 의미가 실제로 적혀 있는지**다. `data_status` 설명이 빠진 채로 배포되면 에이전트가
`no_lookup`(값 없음)을 혼잡으로 오인해도 아무 테스트도 깨지지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.TIME import registry
from app.TIME.schemas import ToolErrorCode

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "app" / "TIME" / "TOOL_CONTRACT.md"


def test_도구_이름이_중복되지_않는다():
    names = [tool["name"] for tool in registry.TOOLS]
    assert len(names) == len(set(names))
    assert set(names) == registry.TOOL_NAMES


def test_로컬과_HTTP_도구가_겹치지_않고_전부_덮는다():
    # 겹치면 라우팅이 어느 어댑터로 갈지 모호해지고, 빠지면 호출 자체가 안 된다.
    assert not (registry.LOCAL_TOOLS & registry.HTTP_TOOLS)
    assert registry.LOCAL_TOOLS | registry.HTTP_TOOLS == registry.TOOL_NAMES


def test_tool_names_순서가_정의_순서를_유지한다():
    # LLM 요청의 tools 배열 순서가 프롬프트 캐시 프리픽스에 들어간다. 순서가 흔들리면
    # 매 요청 캐시가 통째로 무효화된다.
    assert registry.tool_names() == [tool["name"] for tool in registry.TOOLS]


def test_get_tool은_없는_이름에_None을_준다():
    assert registry.get_tool(registry.REPLAN_ROUTE) is not None
    assert registry.get_tool("존재하지_않는_도구") is None


@pytest.mark.parametrize("tool", registry.TOOLS, ids=lambda t: t["name"])
def test_모든_도구가_필수_키와_설명을_갖는다(tool):
    for key in ("name", "description", "input_schema", "output_schema", "errors"):
        assert key in tool, f"{tool['name']}에 {key}가 없다"
    assert tool["description"].strip(), f"{tool['name']} 설명이 비었다"


@pytest.mark.parametrize("tool", registry.TOOLS, ids=lambda t: t["name"])
def test_입력_스키마가_strict하다(tool):
    # additionalProperties를 막아두지 않으면 LLM이 지어낸 인자가 조용히 통과한다.
    schema = tool["input_schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    for name in schema["required"]:
        assert name in schema["properties"], f"{tool['name']}: required {name}가 properties에 없다"


@pytest.mark.parametrize("tool", registry.TOOLS, ids=lambda t: t["name"])
def test_선언한_오류가_실제_코드에_있다(tool):
    valid = {code.value for code in ToolErrorCode}
    for code in tool["errors"]:
        assert code in valid, f"{tool['name']}: 알 수 없는 오류 코드 {code}"


@pytest.mark.parametrize("tool", registry.TOOLS, ids=lambda t: t["name"])
def test_스키마가_JSON_직렬화된다(tool):
    # LLM 요청 body로 그대로 나가므로 직렬화 불가한 값이 섞이면 런타임에 터진다.
    json.dumps(tool, ensure_ascii=False)


def _congestion_status_descriptions() -> list[str]:
    """data_status description을 담은 도구들을 찾아 설명 문자열만 모은다."""
    found = []
    for name in (registry.GET_LINE_CONGESTION, registry.GET_STATION_CONGESTION):
        tool = registry.get_tool(name)
        assert tool is not None
        dumped = json.dumps(tool, ensure_ascii=False)
        matches = re.findall(
            r'"data_status":\s*\{[^}]*"description":\s*"((?:[^"\\]|\\.)*)"', dumped
        )
        assert matches, f"{name}에 data_status description이 없다"
        found.extend(matches)
    return found


@pytest.mark.parametrize(
    "status",
    ["ok", "calibration_fallback", "no_lookup", "segment_truncated", "no_calibration", "no_data"],
)
def test_data_status_6개_값이_전부_설명돼_있다(status):
    # SERVING_CONTRACT.md 2절의 6개 값. 하나라도 설명이 없으면 에이전트가 그 상태를 만났을 때
    # 어떻게 다뤄야 할지 알 수 없다 — 결측을 혼잡으로 읽는 사고가 여기서 난다.
    descriptions = " ".join(_congestion_status_descriptions())
    assert status in descriptions, f"data_status 설명에 {status}가 없다"


def test_결측_상태를_쓰지_말라고_명시한다():
    # 값이 있는 상태(ok·calibration_fallback)와 없는 상태를 구분해 지시하는지 본다.
    descriptions = " ".join(_congestion_status_descriptions())
    assert "null" in descriptions
    assert "말 것" in descriptions or "쓰지" in descriptions


def test_replan은_경로를_그대로_인용하라고_지시한다():
    # 이 문장이 빠지면 LLM이 역 이름·소요시간을 각색한다. 도구 계층이 막을 수 있는 유일한 지점이
    # description이다(값 안 지어내기 원칙).
    tool = registry.get_tool(registry.REPLAN_ROUTE)
    assert tool is not None
    assert "그대로" in tool["description"]


def test_replan_빈_배열이_오류가_아님을_설명한다():
    tool = registry.get_tool(registry.REPLAN_ROUTE)
    assert tool is not None
    assert "빈 배열" in tool["description"]


def test_arrivals_status_4종이_전부_설명돼_있다():
    tool = registry.get_tool(registry.GET_ARRIVALS)
    assert tool is not None
    status = tool["output_schema"]["properties"]["status"]
    assert set(status["enum"]) == {"LIVE", "NO_INFO", "OUTSIDE_WINDOW", "STALE"}
    for value in status["enum"]:
        assert value in status["description"], f"arrivals status 설명에 {value}가 없다"


def test_혼잡도_예측이_실시간이_아님을_밝힌다():
    # 배치 산출물이라는 사실을 숨기면 에이전트가 "지금 혼잡해졌다"고 말하게 된다.
    tool = registry.get_tool(registry.GET_LINE_CONGESTION)
    assert tool is not None
    assert "실시간" in tool["description"] and "예측" in tool["description"]


def test_회신_결과가_표시돼_있다():
    # BE 회신(FROM_BE-time-reroute-contract-01)의 보류·거절·확정 결과를 코드에 남긴다.
    # 스키마는 열지 않으므로 x_pending은 더 이상 없어야 한다.
    tool = registry.get_tool(registry.REPLAN_ROUTE)
    assert tool is not None
    resolved = tool.get("x_resolved")
    assert resolved is not None
    assert resolved["handoff"] == "FROM_BE-time-reroute-contract-01"
    assert resolved["items"]
    assert "x_pending" not in tool


def test_스키마_버전이_semver다():
    assert re.fullmatch(r"\d+\.\d+\.\d+", registry.TOOL_SCHEMA_VERSION)


@pytest.mark.skipif(not CONTRACT_PATH.exists(), reason="TOOL_CONTRACT.md 미작성")
def test_계약_문서가_도구_목록과_일치한다():
    # SERVING_CONTRACT.md ↔ test_crowd_serving_contract.py와 같은 방식 — 코드만 고치면 CI가 막힌다.
    # (test_도구_이름이_중복되지_않는다 등이 registry.TOOLS 자체를 검증하므로 여기는 문서 대조만 본다)
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    for name in registry.tool_names():
        assert f"`{name}`" in text, f"TOOL_CONTRACT.md에 {name}가 없다"
    assert registry.TOOL_SCHEMA_VERSION in text


def test_bike_stations_nearby가_도구_목록_맨_뒤에_있다():
    # 1.1절 순서 고정 — 기존 도구 뒤에 추가해야 tools 배열 순서가 흔들리지 않는다
    # (LLM 요청의 tools 순서가 프롬프트 캐시 프리픽스에 들어간다).
    assert registry.TOOLS[-1]["name"] == registry.BIKE_STATIONS_NEARBY


def test_bike_stations_nearby는_HTTP_도구다():
    assert registry.BIKE_STATIONS_NEARBY in registry.HTTP_TOOLS
    assert registry.BIKE_STATIONS_NEARBY not in registry.LOCAL_TOOLS


def test_bike_stations_nearby_설명이_availableBikes_의미를_밝힌다():
    # availableBikes를 도착 예측으로 오인하면 안 된다 — get_eta_stock으로 유도하는 문장이 있는지 본다.
    tool = registry.get_tool(registry.BIKE_STATIONS_NEARBY)
    assert tool is not None
    assert "availableBikes" in tool["description"]
    assert "get_eta_stock" in tool["description"]
