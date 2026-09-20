"""에이전트 도구 정의(S15P21A104-202).

도구 스키마를 **표준 JSON Schema**로 한 벌만 정의한다. Anthropic `tools`든 OpenAI `functions`든
이 한 벌에서 변환기 한 겹으로 나온다 — LLM 게이트웨이가 확정되기 전에 스키마를 특정 벤더 모양으로
굳히면 게이트웨이가 바뀔 때 전부 다시 써야 한다.

스키마의 `description`은 **LLM이 실제로 읽는 유일한 설명**이다. 특히 `data_status`·`pred_source`의
의미를 여기 박아두는 것이 이 티켓의 핵심이다 — 결측(`no_lookup` 등)을 혼잡으로 오인하는 사고를
프롬프트가 아니라 스키마 단계에서 막는다. 원문은 `app/CROWD/SERVING_CONTRACT.md` 2절.
"""

from __future__ import annotations

from typing import Any

TOOL_SCHEMA_VERSION = "1.0.0"
"""도구 스키마 판. 필드 추가는 minor, 삭제·의미 변경은 major. 이력은 TOOL_CONTRACT.md."""

# ── 도구 이름 상수 ──
# 어댑터·가드·테스트가 같은 문자열을 쓰도록 한곳에 둔다. 오타가 런타임까지 가지 않게 한다.
GET_STATION_CONGESTION = "get_station_congestion"
GET_LINE_CONGESTION = "get_line_congestion"
GET_ETA_STOCK = "get_eta_stock"
GET_ARRIVALS = "get_arrivals"
REPLAN_ROUTE = "replan_route"

LOCAL_TOOLS = frozenset({GET_STATION_CONGESTION, GET_LINE_CONGESTION, GET_ETA_STOCK})
"""같은 프로세스의 app.CROWD / app.BIKE 함수를 직접 부르는 도구."""

HTTP_TOOLS = frozenset({GET_ARRIVALS, REPLAN_ROUTE})
"""BE HTTP API를 부르는 도구."""

# ── 공통 설명 조각 ──
# 같은 문장을 도구마다 다시 쓰면 한쪽만 고쳐지고 엇갈린다.

_DATA_STATUS_DESC = (
    "이 셀의 신뢰 상태. 'ok'=정상 사용. "
    "'calibration_fallback'=값은 있으나 공휴일에 일요일 배율을 빌려 쓴 값 — 쓰되 근거 문장에 "
    "보정 사실을 밝힐 것. "
    "'no_lookup'/'segment_truncated'/'no_calibration'=값이 null이라 판단 근거로 쓰지 말 것 "
    "(결측이지 혼잡이 아니다). "
    "'no_data'=그 날짜 배치 미실행."
)

_PRED_SOURCE_DESC = (
    "예측값 출처. 'model'=정상. "
    "'lookup_negative'=모델이 음수를 내서 기준선 평균으로 대체된 셀 — 정확도가 낮다."
)

_CONGESTION_PCT_DESC = (
    "보정 혼잡도(%). 정원 100% 기준. data_status가 ok/calibration_fallback이 아니면 null."
)

_GRADE_DESC = "혼잡 등급(0부터). 임계값은 배치 메타의 grade_thresholds. 결측이면 null."


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """도구 입력 스키마의 공통 뼈대. strict 모드를 쓸 수 있도록 additionalProperties를 막는다."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": GET_LINE_CONGESTION,
        "description": (
            "한 호선의 모든 역 혼잡도를 특정 30분 슬롯 기준으로 한 번에 조회한다. "
            "앞쪽 역의 혼잡이 오를지 판단하는 주 입력이다. "
            "예측 표는 하루 1회 배치 산출물이라 실시간 값이 아니다 — "
            "'지금 혼잡해졌다'가 아니라 '그 시점에 혼잡할 것으로 예측된다'로 해석할 것."
        ),
        "input_schema": _obj(
            {
                "date": {
                    "type": "string",
                    "format": "date",
                    "description": "조회 날짜 YYYY-MM-DD",
                },
                "line": {
                    "type": "string",
                    "description": "호선명. '2호선' 형식 그대로",
                },
                "time_slot_30min": {
                    "type": "string",
                    "pattern": "^([01][0-9]|2[0-3]):(00|30)$",
                    "description": "30분 슬롯 시작 시각. 예: '08:30'",
                },
            },
            ["date", "line", "time_slot_30min"],
        ),
        "output_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "format": "date"},
                "line": {"type": "string"},
                "time_slot_30min": {"type": "string"},
                "stations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "station_no": {"type": "integer"},
                            "station_name": {"type": ["string", "null"]},
                            "direction": {
                                "type": "string",
                                "description": "상선/하선 또는 내선/외선(2호선)",
                            },
                            "congestion_pct": {
                                "type": ["number", "null"],
                                "description": _CONGESTION_PCT_DESC,
                            },
                            "grade": {"type": ["integer", "null"], "description": _GRADE_DESC},
                            "data_status": {"type": "string", "description": _DATA_STATUS_DESC},
                            "pred_source": {"type": "string", "description": _PRED_SOURCE_DESC},
                        },
                    },
                },
            },
        },
        "errors": ["NOT_FOUND", "INVALID_INPUT"],
    },
    {
        "name": GET_STATION_CONGESTION,
        "description": (
            "역 하나의 하루치 30분 슬롯 혼잡도를 조회한다. "
            "특정 역의 시간대별 추이를 볼 때 쓴다 — 노선 전체 비교는 get_line_congestion을 쓸 것. "
            "존재하지 않는 역은 오류가 아니라 빈 slots로 돌아온다."
        ),
        "input_schema": _obj(
            {
                "date": {"type": "string", "format": "date", "description": "조회 날짜 YYYY-MM-DD"},
                "station_no": {"type": "integer", "description": "역번호(서울시 표준)"},
                "direction": {
                    "type": ["string", "null"],
                    "description": "상선/하선/내선/외선. 생략하면 전 방향",
                },
            },
            ["date", "station_no"],
        ),
        "output_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "format": "date"},
                "station_no": {"type": "integer"},
                "station_name": {"type": ["string", "null"]},
                "line": {"type": ["string", "null"]},
                "train_capacity": {"type": ["integer", "null"]},
                "lag1d_available": {
                    "type": ["boolean", "null"],
                    "description": (
                        "전날 실측이 있었는지. false면 1주 전 시차만으로 예측된 표라 "
                        "정확도가 낮다 — 근거로 쓸 때 감안할 것."
                    ),
                },
                "slots": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "time_slot_30min": {"type": "string"},
                            "direction": {"type": "string"},
                            "congestion_pct": {
                                "type": ["number", "null"],
                                "description": _CONGESTION_PCT_DESC,
                            },
                            "grade": {"type": ["integer", "null"], "description": _GRADE_DESC},
                            "data_status": {"type": "string", "description": _DATA_STATUS_DESC},
                            "pred_source": {"type": "string", "description": _PRED_SOURCE_DESC},
                        },
                    },
                },
            },
        },
        "errors": ["NOT_FOUND", "INVALID_INPUT"],
    },
    {
        "name": GET_ETA_STOCK,
        "description": (
            "따릉이 대여소의 '도착 시점' 예상 재고를 조회한다. 현재 재고가 아니라 "
            "eta_minutes 뒤 예측값이다. 지하철 대신 따릉이로 갈아탈 수 있는지 볼 때 쓴다. "
            "p_empty가 높으면 도착했을 때 자전거가 없을 가능성이 크다."
        ),
        "input_schema": _obj(
            {
                "rental_id": {"type": "string", "description": "대여소 ID"},
                "eta_minutes": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 1440,
                    "description": (
                        "도착까지 예상 분. 학습 horizon은 5·10·15·30이라 그 밖의 값은 "
                        "가장 가까운 값으로 근사되고, 30 초과는 전부 30 기준 예측이 된다."
                    ),
                },
            },
            ["rental_id", "eta_minutes"],
        ),
        "output_schema": {
            "type": "object",
            "properties": {
                "rental_id": {"type": "string"},
                "eta_minutes": {"type": "integer"},
                "current_stock": {"type": "integer", "description": "실시간 스냅샷의 현재 재고"},
                "predicted_stock": {"type": "number", "description": "도착 시점 예측 재고"},
                "p_empty": {
                    "type": ["number", "null"],
                    "description": "도착 슬롯 0대 확률(0~1). 분류기 없으면 null",
                },
                "p_full": {"type": ["number", "null"], "description": "도착 슬롯 만차 확률(0~1)"},
                "source": {
                    "type": "string",
                    "description": (
                        "'lightgbm'=정상. "
                        "'lightgbm_global_fallback'=학습 시점에 없던 신규 대여소라 "
                        "역 무관 전역 평균으로 낸 값 — 정확도가 낮다."
                    ),
                },
                "model_horizon_min": {
                    "type": "integer",
                    "description": "실제 예측에 쓰인 horizon(분). 요청값과 다를 수 있다",
                },
            },
        },
        "errors": ["NOT_FOUND", "UPSTREAM_UNAVAILABLE", "INVALID_INPUT"],
    },
    {
        "name": GET_ARRIVALS,
        "description": (
            "역의 실시간 열차 도착 정보를 조회한다. 사용자가 지금 어느 열차에 타고 있는지, "
            "다음 열차가 언제 오는지 확인할 때 쓴다. "
            "trains가 비어 있어도 오류가 아니다 — status로 이유를 구분할 것."
        ),
        "input_schema": _obj(
            {
                "station_id": {"type": "string", "description": "역 ID"},
                "route_id": {
                    "type": ["string", "null"],
                    "description": "특정 노선만 볼 때. 생략하면 그 역의 전 노선",
                },
            },
            ["station_id"],
        ),
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["LIVE", "NO_INFO", "OUTSIDE_WINDOW", "STALE"],
                    "description": (
                        "'LIVE'=실시간 정보 있음. "
                        "'NO_INFO'=확인할 도착 정보가 없음. "
                        "'OUTSIDE_WINDOW'=운행 시간대 밖. "
                        "'STALE'=수집이 지연돼 값이 오래됨 — 도착 시각을 그대로 믿지 말 것. "
                        "LIVE가 아니면 trains는 비어 있다."
                    ),
                },
                "trains": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "train_id": {"type": "string"},
                            "direction": {"type": "string", "description": "방면"},
                            "arrival_time": {"type": "string", "format": "date-time"},
                            "updated_at": {"type": "string", "format": "date-time"},
                            "source": {"type": "string"},
                        },
                    },
                },
                "updated_at": {"type": ["string", "null"], "format": "date-time"},
            },
        },
        "errors": ["UPSTREAM_UNAVAILABLE", "INVALID_INPUT"],
    },
    {
        "name": REPLAN_ROUTE,
        "description": (
            "현재 위치(경계역)에서 목적지까지 남은 경로를 다시 탐색한다. "
            "하차 후보역마다 boundary_id를 바꿔 각각 호출하고 결과를 비교하는 방식으로 쓴다. "
            "빈 배열은 오류가 아니라 '대안 없음'이며, 그때는 기존 안내를 유지해야 한다. "
            "반환된 경로의 역 이름·소요시간·거리를 임의로 바꾸지 말 것 — 그대로 인용한다."
        ),
        "input_schema": _obj(
            {
                "step": {"type": "integer", "minimum": 0, "description": "원본 legs 인덱스"},
                "boundary_id": {
                    "type": "string",
                    "description": "현 경계 노드 ID. 여기서부터 다시 탐색한다",
                },
                "dest_station_id": {"type": "string", "description": "목적지 역 ID"},
                "modes": {
                    "type": ["array", "null"],
                    "items": {"type": "string", "enum": ["SUBWAY", "BUS", "BIKE", "WALK"]},
                    "description": "허용 수단. 생략하면 전부",
                },
                "priority": {
                    "type": ["string", "null"],
                    "enum": ["fast", "calm", None],
                    "description": "fast=빠른 경로, calm=덜 혼잡한 경로. 기본 fast",
                },
            },
            ["step", "boundary_id", "dest_station_id"],
        ),
        "output_schema": {
            "type": "array",
            "description": "잔여 경로 후보. 최대 3개, 소요시간순",
            "items": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "이 대안을 제시하는 이유"},
                    "source": {
                        "type": "string",
                        "description": "ALGORITHM=탐색 결과 그대로",
                    },
                    "route": {
                        "type": "object",
                        "description": (
                            "잔여 경로. legs는 경계역에서 시작해 목적지에서 끝나고, "
                            "totalMinutes는 legs 소요시간 합과 일치한다."
                        ),
                    },
                },
            },
        },
        "errors": ["UPSTREAM_UNAVAILABLE", "INVALID_INPUT"],
        # TO_BE-time-reroute-contract-01 회신 대기 — 회신이 오면 아래를 스키마에 반영한다.
        "x_pending": {
            "handoff": "TO_BE-time-reroute-contract-01",
            "fields": [
                "input.exclude_route_ids — 현재 타고 있는 노선을 후보에서 배제·후순위화",
                "output.source에 'AGENT' 값 추가",
                "output.reason을 에이전트가 생성 (BE 고정 문구는 fallback)",
            ],
        },
    },
]

_BY_NAME: dict[str, dict[str, Any]] = {tool["name"]: tool for tool in TOOLS}

TOOL_NAMES: frozenset[str] = frozenset(_BY_NAME)


def get_tool(name: str) -> dict[str, Any] | None:
    """도구 정의 하나. 없으면 None — 호출자가 INVALID_INPUT으로 변환한다."""
    return _BY_NAME.get(name)


def tool_names() -> list[str]:
    """정의 순서를 유지한 도구 이름 목록.

    순서를 유지하는 이유: LLM 요청의 `tools` 배열 순서가 프롬프트 캐시 프리픽스에 들어간다.
    매번 순서가 달라지면 캐시가 통째로 무효화된다.
    """
    return [tool["name"] for tool in TOOLS]
