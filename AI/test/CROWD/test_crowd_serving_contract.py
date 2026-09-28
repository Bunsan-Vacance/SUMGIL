"""197 C부 — 프로덕션 출력과 셀프 명세(`SERVING_CONTRACT.md`)가 어긋나면 실패한다.

BE·FE가 읽는 계약 문서가 코드보다 늦게 갱신되는 것을 막는 장치다. 명세는 사람이 기억해서
고치는 게 아니라 **테스트가 붙들어 둔다** — 산출물 컬럼·메타 키·API 경로·응답 필드를 바꾸면
문서를 같이 고치지 않는 한 CI가 막는다.

대조하는 짝:

| 코드 | 명세 |
| --- | --- |
| `batch_predict.OUTPUT_COLS` | 1절 컬럼 표 + "실제 2행" JSON |
| `batch_predict.DATA_STATUS_VALUES` (+ `API_ONLY_DATA_STATUS`) | 2절 상태 표 |
| `batch_predict.META_KEYS` | 3절 메타 표 |
| `settings.grade_thresholds` | 2절 등급 임계값 표 |
| FastAPI 라우트·쿼리 파라미터(OpenAPI) | 4절 소제목·파라미터 표 |
| `schemas.py` 응답 모델 필드 | 4절 응답 예시 JSON |

문서 쪽 표를 파싱하므로 표 모양이 바뀌면 이 테스트가 먼저 깨진다 — 그것도 의도다(계약 문서가
기계로 읽히는 모양을 유지하게 만든다).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.CROWD import schemas
from app.CROWD.pipeline.batch_predict import (
    API_ONLY_DATA_STATUS,
    DATA_STATUS_VALUES,
    LINK_OUTPUT_COLS,
    META_KEYS,
    OUTPUT_COLS,
    TRAIN_OUTPUT_COLS,
)
from app.main import app

CONTRACT = Path(schemas.__file__).with_name("SERVING_CONTRACT.md")

# 명세가 코드 옆에 없으면 계약 자체가 없는 것이므로 스킵이 아니라 실패다.
assert CONTRACT.exists(), f"서빙 계약 문서가 없다: {CONTRACT}"
TEXT = CONTRACT.read_text(encoding="utf-8")

SUBHEADING = "\n### "
CODE = re.compile(r"`([^`]+)`")
HEADING = re.compile(r"^###\s+4\.\d+\s+`(GET|POST|PUT|PATCH|DELETE)\s+(/[^`]+)`", re.MULTILINE)


def section(number: str) -> str:
    """`## <number>.`로 시작하는 절의 본문(다음 `## ` 직전까지)."""
    parts = re.split(r"^## ", TEXT, flags=re.MULTILINE)
    for part in parts:
        if part.startswith(f"{number}."):
            return part
    raise AssertionError(f"명세에 {number}절이 없다")


def first_cells(body: str) -> list[str]:
    """표의 각 행에서 첫 칸에 있는 백틱 토큰만 뽑는다(헤더·구분선·설명 행은 자동으로 빠진다)."""
    out = []
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cell = line.split("|")[1].strip().replace("**", "")
        m = CODE.fullmatch(cell)
        if m:
            out.append(m.group(1))
    return out


def before_subheading(body: str) -> str:
    """절 본문에서 첫 `###` 소제목 앞부분만(한 절에 표가 여럿일 때 첫 표만 보려고)."""
    return body.split(SUBHEADING)[0]


def json_blocks(body: str) -> list:
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)```", body, re.DOTALL)]


def model_fields(model) -> set[str]:
    return set(model.model_fields)


# --- 1절: 배치 산출물 컬럼 ------------------------------------------------------


def test_output_columns_match_contract_table():
    """`OUTPUT_COLS`와 1절 컬럼 표가 순서까지 같아야 한다."""
    assert first_cells(section("1")) == OUTPUT_COLS


def test_sample_rows_carry_every_output_column():
    """1절 "실제 2행" 예시가 실제 컬럼을 전부 담고 있어야 한다 — 예시만 낡는 것을 막는다."""
    rows = json_blocks(section("1"))[0]
    assert rows, "1절에 예시 행이 없다"
    for row in rows:
        assert list(row) == OUTPUT_COLS


# --- 2절: data_status ----------------------------------------------------------


def test_data_status_table_matches_constants():
    """2절 표 = 표에 실리는 값 + API 전용 값. 상태를 추가하면 문서도 같이 고쳐야 한다."""
    documented = first_cells(before_subheading(section("2")))
    assert set(documented) == set(DATA_STATUS_VALUES) | set(API_ONLY_DATA_STATUS)


def test_grade_thresholds_table_matches_settings():
    """2절 "등급 임계값" 표의 등급 수가 설정값(`crowd_grade_thresholds`)과 맞아야 한다.

    임계값 n개면 등급은 n+1개다. FE 논의로 3단계 ↔ 4단계가 바뀔 수 있는 값이라 문서만 남는 것을 막는다.
    """
    grades = first_cells(section("2").split(SUBHEADING, 1)[1])
    thresholds = get_settings().grade_thresholds
    assert [int(g) for g in grades] == list(range(len(thresholds) + 1))
    for value in thresholds:
        assert f"{value:g}%" in section("2"), f"임계값 {value:g}가 2절 표에 없다"


# --- 3절: .meta.json -----------------------------------------------------------


def test_meta_key_table_matches_meta_keys():
    """`META_KEYS`와 3절 메타 표가 순서까지 같아야 한다(`validated_meta`가 이 순서로 쓴다)."""
    assert first_cells(section("3")) == list(META_KEYS)


# --- 7절: 열차·노드 표 ------------------------------------------------------------


def test_train_output_columns_match_contract_table():
    """`TRAIN_OUTPUT_COLS`와 7절 컬럼 표가 순서까지 같아야 한다(239)."""
    assert first_cells(section("7")) == TRAIN_OUTPUT_COLS


# --- 8절: 링크(from/to) 표 -------------------------------------------------------


def test_link_output_columns_match_contract_table():
    """`LINK_OUTPUT_COLS`와 8절 컬럼 표가 순서까지 같아야 한다(244)."""
    assert first_cells(section("8")) == LINK_OUTPUT_COLS


# --- 4절: API ------------------------------------------------------------------


def documented_endpoints() -> dict[tuple[str, str], str]:
    """{(method, path): 소제목 이후 본문}"""
    body = section("4")
    found = list(HEADING.finditer(body))
    assert found, "4절에 `### 4.x `GET /경로`` 소제목이 없다"
    out = {}
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(body)
        out[(m.group(1).lower(), m.group(2))] = body[m.end() : end]
    return out


def crowd_routes() -> dict[tuple[str, str], dict]:
    spec = app.openapi()["paths"]
    return {
        (method, path): op
        for path, ops in spec.items()
        for method, op in ops.items()
        if path.startswith("/crowd")
    }


def test_documented_endpoints_match_router():
    assert set(documented_endpoints()) == set(crowd_routes())


@pytest.mark.parametrize("key", sorted(crowd_routes()))
def test_documented_parameters_match_openapi(key):
    """파라미터 표(이름·위치·필수)가 OpenAPI와 일치해야 한다. 표가 없으면 파라미터도 없어야 한다."""
    body = documented_endpoints()[key]
    documented = set()
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        m = re.fullmatch(r"`([^`]+)`\s*\((path|query)\)", cells[0].replace("**", ""))
        if m:
            documented.add((m.group(1), m.group(2), cells[1] == "O"))

    actual = {
        (p["name"], p["in"], bool(p.get("required", False)))
        for p in crowd_routes()[key].get("parameters", [])
    }
    assert documented == actual


@pytest.mark.parametrize(
    ("key", "model", "nested"),
    [
        (("get", "/crowd/meta"), schemas.CrowdMetaResponse, None),
        (
            ("get", "/crowd/stations/{station_no}/congestion"),
            schemas.StationCongestionResponse,
            ("slots", schemas.SlotCongestion),
        ),
        (
            ("get", "/crowd/lines/{line}/congestion"),
            schemas.LineCongestionResponse,
            ("stations", schemas.LineStationSnapshot),
        ),
    ],
)
def test_response_examples_cover_every_schema_field(key, model, nested):
    """응답 예시 JSON의 키가 pydantic 모델 필드와 정확히 같아야 한다 — 필드를 늘리면 예시도 고친다."""
    blocks = json_blocks(documented_endpoints()[key])
    assert blocks, f"{key} 소제목 아래에 응답 예시가 없다"
    example = blocks[0]
    assert set(example) == model_fields(model)

    if nested is not None:
        field, item_model = nested
        items = example[field]
        assert items, f"{key}의 `{field}` 예시가 비어 있다"
        for item in items:
            assert set(item) == model_fields(item_model)


def test_examples_are_actually_servable():
    """예시가 스키마 모양만 맞고 값 타입이 어긋나는 것을 막는다 — 모델로 역직렬화해 본다."""
    for key, model in (
        (("get", "/crowd/meta"), schemas.CrowdMetaResponse),
        (("get", "/crowd/stations/{station_no}/congestion"), schemas.StationCongestionResponse),
        (("get", "/crowd/lines/{line}/congestion"), schemas.LineCongestionResponse),
    ):
        model.model_validate(json_blocks(documented_endpoints()[key])[0])


def test_error_contract_matches_router():
    """4절이 약속한 404 본문 모양(`detail`)이 실제 응답과 같아야 한다."""
    assert "**404**" in section("4")
    client = TestClient(app)
    res = client.get("/crowd/stations/150/congestion", params={"date": "1999-01-01"})
    assert res.status_code == 404
    assert set(res.json()) == {"detail"}
