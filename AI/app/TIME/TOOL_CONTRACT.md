# TIME 에이전트 도구 계층 — 계약 (S15P21A104-202)

작성 2026-09-20 · 브랜치 `feat/TIME-agent-tool-layer` · 스키마 판 **1.1.0**

> **이 문서는 도구 계층의 계약이다. 아래가 바뀌면 같은 커밋에서 이 문서를 고친다.**
> `registry.TOOL_SCHEMA_VERSION` · `registry.TOOLS`의 도구 이름·입출력 스키마 ·
> `schemas.ToolErrorCode` 값 · 어댑터의 오류 매핑 · 가드 기본 예산.
>
> **이 문서는 테스트가 강제한다.** `test/TIME/test_time_registry.py`의
> `test_계약_문서가_도구_목록과_일치한다`가 도구 이름 6종과 스키마 판을 이 문서와 대조한다.
> 코드만 고치면 CI가 막힌다(`SERVING_CONTRACT.md` ↔ `test_crowd_serving_contract.py`와 같은 방식).

---

## 0. 이 계층이 하는 일

LLM 에이전트(203)가 호출할 도구를 **한 벌**로 정의하고, 실제 구현으로 잇고, 폭주를 막는다.

```
에이전트 루프(203)
      │  도구 이름 + 인자
      ▼
  ToolGuard.run()        ← 예산·레이트·로그 (guard.py)
      │
      ▼
  CompositeAdapter       ← 이름으로 Local/Http 라우팅 (adapters.py)
      ├─ LocalAdapter ── app.CROWD.service · app.BIKE.service (같은 프로세스)
      └─ HttpAdapter  ── BE /api/... (HTTP)
```

스키마는 **표준 JSON Schema 한 벌**이다. Anthropic `tools`든 OpenAI `functions`든 여기서 변환기
한 겹으로 나온다 — LLM 게이트웨이가 확정되기 전에 벤더 모양으로 굳히지 않기 위해서다.

---

## 1. 도구 6종

| 도구 | 경로 | 원천 | 반환 |
| --- | --- | --- | --- |
| `get_line_congestion` | 로컬 | `app.CROWD.service.line_congestion` | 객체 |
| `get_station_congestion` | 로컬 | `app.CROWD.service.station_congestion` | 객체 |
| `get_eta_stock` | 로컬 | `app.BIKE.service.predict_eta_stock` | 객체 |
| `get_arrivals` | HTTP | `GET /api/transit/arrivals` (S15P21A104-192) | 객체 |
| `replan_route` | HTTP | `POST /api/routes/replan` (S15P21A104-193) | **배열** |
| `bike_stations_nearby` | HTTP | `GET /api/bike-stations/nearby` | **배열** |

입출력 필드는 `registry.TOOLS`가 원본이다. 이 문서에 복사하지 않는다 — 두 벌이 되면 갈라진다.

`LOCAL_TOOLS`와 `HTTP_TOOLS`는 서로 겹치지 않고 합치면 전체가 된다(테스트로 고정).

### 1.1 도구 순서는 흔들면 안 된다

`registry.tool_names()`는 정의 순서를 유지한다. LLM 요청의 `tools` 배열 순서가 프롬프트 캐시
프리픽스에 들어가므로, 순서가 매번 달라지면 캐시가 통째로 무효화된다.

---

## 2. 오류 — 예외가 아니라 값이다

**도구는 예외를 던지지 않는다.** 실패도 `ToolError`라는 정상 반환값으로 낸다. 에이전트 루프
한가운데서 예외가 올라오면 루프가 죽고, LLM은 무슨 일이 있었는지 알 수 없다.

| 코드 | 뜻 | retryable | 나오는 상황 |
| --- | --- | --- | --- |
| `INVALID_INPUT` | 인자가 스키마에 안 맞는다 | ✗ | 날짜 형식 오류, 없는 도구 이름, BE 400 |
| `NOT_FOUND` | **없다는 걸 확인했다** | ✗ | 배치 미실행 표, 실시간 재고 없음, BE 404 |
| `UPSTREAM_UNAVAILABLE` | **물어보지 못했다** | ✓ | BE 미기동·타임아웃, 모델 아티팩트 장애, 예상 못 한 예외 |
| `RATE_LIMITED` | 호출이 너무 잦다 | ✓ | 초당 한도 초과 |
| `BUDGET_EXCEEDED` | 세션 예산 소진 | ✗ | 총·도구별 호출 한도 초과 |

### 2.1 `NOT_FOUND`와 `UPSTREAM_UNAVAILABLE`을 섞지 않는다

이 구분이 이 계층의 핵심 판단이다. 둘을 뭉개면 **에이전트가 없는 것을 있다고 말하게 된다** —
"물어보지 못했다"를 "없다"로 읽으면 결측을 사실로 단정하기 때문이다. 값 안 지어내기 원칙
(`Docs/Service Design/데이터-검증-리포트.md`)의 도구 계층 판이다.

CROWD 서비스의 `None`은 "그 날짜 예측 표가 없다"(배치 미실행)이고, 존재하지 않는 역은 `None`이
아니라 **빈 `slots`/`stations`로 200**이다 — 둘이 섞이지 않는다.

### 2.2 예상 못 한 예외도 `ToolError`가 된다

명시적으로 번역하는 건 예상한 실패(`LiveStockMissing`·`ModelUnavailable`·인자 파싱)뿐이다.
서비스가 새 예외를 추가하면(예: `AvgDataMissing`) 그대로 새어나가 루프를 죽이므로,
두 어댑터의 `call()` 끝에 마지막 그물을 쳐 `UPSTREAM_UNAVAILABLE`로 바꾼다.

**가드가 아니라 어댑터에 둔 이유**: 가드 없이 어댑터만 쓰는 호출 경로(203 PoC·테스트)에서도
불변식이 지켜져야 한다.

---

## 3. 결측 상태를 스키마에 박아둔다

이 티켓의 핵심 가치다. `data_status`·`pred_source`·`source`·`status`의 의미를 도구 출력 스키마의
`description`에 그대로 넣는다 — **프롬프트가 아니라 스키마 단계에서** 막아야 203에서 프롬프트를
고쳐도 이 보호가 안 풀린다.

### 3.1 `data_status` (혼잡도 2종) — 원문은 `app/CROWD/SERVING_CONTRACT.md` 2절

| 값 | 에이전트가 해야 할 일 |
| --- | --- |
| `ok` | 쓴다 |
| `calibration_fallback` | 쓰되 **근거 문장에 공휴일 보정 사실을 밝힌다** (일요일 배율을 빌려 쓴 값) |
| `no_lookup` · `segment_truncated` · `no_calibration` | **판단 근거로 쓰지 않는다** — 값이 null이다. 결측이지 혼잡이 아니다 |
| `no_data` | 배치 미실행. 트리거 자체를 포기한다 |

`test_data_status_6개_값이_전부_설명돼_있다`가 6개 값이 스키마 설명에 남아 있는지 검사한다.

### 3.2 그 밖의 신뢰 신호

| 필드 | 주의할 값 |
| --- | --- |
| `pred_source` | `lookup_negative` — 모델이 음수를 내서 기준선 평균으로 대체된 셀 |
| `lag1d_available` | `false` — 전날 실측 없이 1주 전 시차만으로 예측된 표 |
| `source` (따릉이) | `lightgbm_global_fallback` — 학습에 없던 신규 대여소라 전역 평균으로 낸 값 |
| `status` (도착) | `STALE` — 수집 지연. 도착 시각을 그대로 믿지 않는다 |

### 3.3 혼잡도는 실시간이 아니다

CROWD는 **하루 1회 배치** 산출물이다. `get_line_congestion` 설명에 이 사실을 넣어, 에이전트가
"지금 혼잡해졌다"가 아니라 **"그 시점에 혼잡할 것으로 예측된다"**로 말하게 한다.

### 3.4 경로는 그대로 인용한다

`replan_route` 설명은 "반환된 경로의 역 이름·소요시간·거리를 임의로 바꾸지 말 것"을 명시한다.
LLM이 경로를 각색하는 것을 도구 계층이 막을 수 있는 유일한 지점이 `description`이다.
빈 배열은 오류가 아니라 **"대안 없음"**이고, 그때는 기존 안내를 유지한다.

---

## 4. 어댑터

### 4.1 로컬 — 지연 import

`app.CROWD.service` / `app.BIKE.service`는 pandas와 모델 아티팩트를 끌어오므로 **모듈 최상단이
아니라 호출 시점에 import**한다. 도구 계층을 import했다는 이유만으로 서빙 기동이 느려지지 않게
한다(`AI/CLAUDE.md` 서빙 경로 규약).

### 4.2 HTTP — 주소가 없어도 죽지 않는다

`base_url`이 없어도 **생성·import는 성공하고, 호출 시점에만** `UPSTREAM_UNAVAILABLE`을 돌려준다.
BE 주소가 아직 확정되지 않았는데(→ 6절) 주소가 없다고 계층 전체가 죽으면 로컬 도구 3종까지
못 쓰게 된다. 에이전트 입장에서는 "BE가 안 떠 있는 것"과 같은 상황이다.

| 항목 | 값 |
| --- | --- |
| 타임아웃 | 2.0초 (`DEFAULT_HTTP_TIMEOUT_SECONDS`) |
| 응답 래퍼 | `{"data": ...}`가 있으면 벗기고, 없으면 본문 전체 |
| 키 변환 | 도구 스키마 snake_case → BE DTO camelCase (`boundary_id` → `boundaryId`) |
| `requestedAt` | 호출 시점 `Asia/Seoul` offset ISO-8601 |
| 상태코드 | 404→`NOT_FOUND`, 400→`INVALID_INPUT`, 그 밖 4xx·5xx→`UPSTREAM_UNAVAILABLE` |

`modes`·`priority`가 `None`이면 **body에서 키 자체를 뺀다** — 명시적 `null`과 미지정을 BE가 다르게
볼 수 있어 기본값(전 수단 / fast)이 먹게 한다. `bike_stations_nearby`의 `radius_meters`·`limit`도
같은 규칙이다.

`planner.prefetch`가 후보마다 부르는 `replan_route` 호출은 **순차**다. 원래는 스레드 풀로 병렬
호출했으나, BE 회신(`FROM_BE-time-reroute-contract-01` 8번)에 따르면 prod BE가 CPU 1개 전제라
동시 호출도 BE 스레드에서 실질적으로 직렬 처리된다 — 병렬로 보내 봐야 이득이 없고, 오히려 한
재안내 요청이 BE 스레드 여러 개를 동시에 점유해 일반 탐색 요청을 굶긴다.

### 4.3 결과는 JSON 직렬화 가능하다

CROWD 서비스는 `date` 컬럼을 `datetime.date` 객체로 돌려준다. 도구 결과는 그대로 LLM 요청 body로
나가므로 `_jsonable`이 `date`·`datetime`을 ISO 문자열로 맞춘다. **값을 바꾸는 게 아니라 선언한
스키마(`{"format": "date"}`)의 표현으로 맞추는 것**이고, 숫자·문자열은 손대지 않는다.

---

## 5. 가드

`ToolGuard`는 **세션 단위 인스턴스**다. 모듈 전역 싱글턴을 만들지 않는다 — 동시 사용자끼리 예산을
공유하면 안 된다.

| 예산 | 기본값 | 근거 |
| --- | --- | --- |
| 세션당 총 호출 | 20 | 실제 계획(replan 5 + arrivals 1)의 3배 여유 |
| `replan_route` | 3 | BE 회신 K=3 + 순차 호출 권고(8번) — 하차 후보 상한(5)보다 작아 4·5번째 후보는 예산에서 막힌다 |
| 그 밖 도구별 | 10 | |
| 초당 호출 | 10 | BE 부하 보호 |

**권장 경로는 `run(name, fn, args)`** 다 — `check` → 실행 → `record`를 한 덩어리로 묶어 `record`
누락을 구조적으로 막는다. `check()`는 상태를 바꾸지 않고, 예산은 `record()`가 깎는다.

### 5.1 예산이 레이트보다 먼저다

둘 다 걸리면 `BUDGET_EXCEEDED`(retryable=**False**)를 먼저 준다. `RATE_LIMITED`(retryable=True)를
먼저 주면 에이전트가 "기다렸다 다시"를 택해 루프가 안 끊긴다.

### 5.2 로그에 인자 **값**을 남기지 않는다

기록하는 것은 도구명 · 소요 ms · 결과 코드 · **인자의 키 목록**뿐이다. 좌표·역 ID 같은 사용자
이동 정보가 로그에 쌓이는 것을 막는다. `run(args=...)`는 매핑을 받아 키만 뽑고 값은 버린다 —
호출자가 값을 넘길 자리 자체를 두지 않아 규칙이 아니라 구조로 지켜진다.

막힌 호출(blocked)은 로그에는 남기되 예산은 깎지 않는다 — 에이전트가 어디서 벽에 부딪혔는지가
203 루프 디버깅의 주 단서다.

### 5.3 이번 범위가 아닌 것

**LLM 토큰 비용 가드는 없다.** 모델·단가가 정해지지 않았다(→ 6절). 203에서 붙인다.

---

## 6. 회신 결과 — 확정 · 보류 · 거절

`FROM_BE-time-reroute-contract-01`(2026-09-21) 회신을 반영한다. "회신" 칸의 번호는 그 문서 8절
회신 표의 항목 번호다.

| # | 무엇 | 회신 | 지금 상태 |
| --- | --- | --- | --- |
| 1 | `replan_route` 입력 `exclude_route_ids` | **보류**(1번) — BE 216(혼잡 가중 탐색) 이후 하드 제외/가중 페널티 중 방식을 정한다 | 스키마 미개방. 그전까지는 응답에서 현재 `routeId`를 쓰는 대안을 걸러내는 사후 필터링을 쓴다(`planner._replan_caller`). K=3이라 대안이 0개로 걸러질 수 있다는 한계는 BE도 인지하고 있다 |
| 2 | `replan_route` 출력 `source: "AGENT"` | **거절**(2번) — `source`는 "누가 탐색했나"라 경로는 항상 `ALGORITHM`이 맞다. "누가 골랐나"는 축이 다르다 | 스키마 미개방. 에이전트가 고른 이유는 라우터 응답의 별도 필드(`recommendedBy`)에 싣는다 — FE(최진우) 판단이 먼저 필요하다 |
| 3 | `replan_route` 출력 `reason` 생성 주체 | **확정**(3번) — BE 응답 필드에는 LLM 문장을 싣지 않는다. BE 고정 문구는 그대로 유지 | 스키마 미개방. 에이전트 문장은 에이전트(라우터) 응답에 별도로 담는다 |
| 4 | BE `base_url` | **확인**(5번) — `prod` 네임스페이스 Service `be`, 포트 8080. `/api/**` 전부 인증 없음 | 값은 확인됐지만 호출 방향(6번 — AI가 언제 BE를 직접 부르는지, (b)/(c) 중 선택)이 216 이후 결정 대기라 `Settings` 필드·`.env.example` 반영은 그 결정 이후로 미룬다. 생성자 인자로만 받는 지금 방식은 유지 |
| 5 | LLM 게이트웨이 · 사용 가능 모델 | 사용자 확인 | `.env`의 `GMS_API_KEY`만 있음. 스키마 변환기·비용 가드 미구현 |

1~3은 `registry.py`의 `REPLAN_ROUTE` 항목 `x_resolved`에도 같은 근거로 남아 있다. 스키마를 실제로
여는 것은 BE 216 완료·FE 방침 확정 이후다.

---

## 7. 검증

```bash
cd AI
ruff check .
black --check .
python -m pytest -q test/TIME
```

| 파일 | 케이스 |
| --- | --- |
| `test_time_registry.py` | 45 (계약 문서 대조 포함) |
| `test_time_adapters.py` | 39 |
| `test_time_guard.py` | 21 |

테스트는 **실제 parquet·모델 아티팩트·네트워크를 쓰지 않는다.** CROWD·BIKE 서비스는 가짜 모듈로
갈아끼우고(어댑터가 지연 import하므로 `sys.modules` 교체가 먹는다), `requests.request`는
monkeypatch하며, 가드는 시계를 주입받아 `sleep` 없이 검증한다.

---

## 8. 변경 이력

| 판 | 날짜 | 내용 |
| --- | --- | --- |
| 1.0.0 | 2026-09-20 | 최초. 도구 5종·오류 5종·로컬/HTTP 어댑터·가드 |
| 1.1.0 | 2026-09-21 | bike_stations_nearby 도구·순차 호출·replan 예산 3·BE 회신 반영 |
