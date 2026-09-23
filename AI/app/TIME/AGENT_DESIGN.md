# TIME 재탐색 에이전트 — 설계 (S15P21A104-203)

작성 2026-09-21 · 브랜치 `feat/TIME-agent-llm` · 갱신 2026-09-22 · 브랜치 `feat/TIME-reroute-service`

> 도구 계층의 계약은 `TOOL_CONTRACT.md`, 이 문서는 **에이전트 구성의 판단 근거**다.
> 수치 비교는 여기 없다 — 두 구성을 실제로 붙여 재지 않았고, 재는 것은 기준선 대비 비교(계획 7절)의
> 몫이다. 이 문서는 "왜 이 모양으로 시작하는가"를 정성적으로 적는다.

---

## 1. 구성 비교 — 단일 LLM 호출 vs 상태 그래프 프레임워크

203 범위의 "단일 LLM 함수 호출 vs 상태 그래프 프레임워크 비교 1회"다. 결론을 먼저 적으면
**프리페치 후 단일 호출(1턴)**로 시작하고, 아래 1.4절의 조건이 생기면 그때 그래프로 옮긴다.

### 1.1 두 구성이 무엇인가

| | 단일 호출 (채택) | 상태 그래프 프레임워크 (LangGraph류) |
| --- | --- | --- |
| 누가 도구를 고르나 | **규칙.** 트리거(①)가 문제 대여소를 정하고, 프리페치(③)가 필요한 조회를 다 끝낸다 | **LLM.** 노드마다 다음에 부를 도구를 LLM이 정한다 |
| LLM 턴 수 | 1 | 2~4 (도구 선택 → 결과 읽기 → 재선택 …) |
| LLM이 보는 것 | 완성된 `AgentContext` 한 벌 | 부분 결과의 누적 |
| LLM이 내는 것 | `chosen_index` + `reason` | 도구 호출 인자 + 최종 답 |

**우리도 상태 그래프를 갖고 있다.** ① 트리거 → ② 후보 → ③ 프리페치 → ④ 선택 → ⑤ 문장은 상태
그래프다. 차이는 **그래프의 전이를 누가 결정하느냐**다 — 우리는 ①②③의 전이가 전부 결정론이고
LLM은 ④⑤ 안에서만 산다. "프레임워크를 쓰지 않는다"가 아니라 **"LLM에게 전이를 맡기지 않는다"**가
정확한 표현이다.

### 1.2 다섯 축 비교

| 축 | 단일 호출 | 상태 그래프 | 판정 |
| --- | --- | --- | --- |
| **턴 수·지연** | 1턴. LLM 2~4초 + 도구 ~10ms | 2~4턴. 5~15초. 매 턴이 LLM 왕복 | 단일. 재안내는 이동 중 팝업이라 지연이 곧 무용 |
| **의존성 무게** | `requests` 하나. 이미 있다 | 프레임워크 + 그 의존 트리. 서빙 경로에 실린다 | 단일. `AI/CLAUDE.md` 서빙 경로 규약(무거운 의존은 `pipeline/`에) |
| **재현성 (204 하네스)** | 같은 `AgentContext` → 같은 프롬프트. 표본을 파일로 저장하면 **입력이 완전히 고정**된다 | 중간 턴의 도구 선택이 매번 달라져 같은 표본에서 다른 경로를 탄다. 규칙 기준선과 **같은 입력 조건이 깨진다** | 단일. `AI/CLAUDE.md` 모델 비교 하드 룰 2·3번을 구조로 지킨다 |
| **폴백 복잡도** | 실패·탈락 지점이 한 곳(`AgentStrategy.decide`). `RuleStrategy`로 한 번 떨어진다 | 어느 노드에서 죽었느냐에 따라 폴백이 다르다. 부분 상태를 규칙 전략에 넘길 방법이 필요하다 | 단일 |
| **부분 실패 처리** | 프리페치가 실패를 `CandidateContext.error`로 남기고 LLM은 그것을 **읽기만** 한다 | LLM이 실패를 보고 재시도·우회를 결정한다. 유연하지만 **"모른다"를 "없다"로 읽을 기회**가 턴마다 생긴다 | 단일. 값 안 지어내기 원칙의 도구 계층 판(`TOOL_CONTRACT.md` 2.1절) |

다섯 축 모두 단일 호출이다. **다만 이는 지금 문제의 모양 때문이다** — 트리거가 문제를 이미 알고,
필요한 조회가 사전에 열거되고(대여소 1곳 + 근처 N곳), 후보가 5개 이하다. 문제가 이 모양을 벗어나면
판정이 바뀐다(1.4절).

### 1.3 채택 구성의 비용 — 숨기지 않는다

- **LLM이 도구 결과를 전부 받는다.** 후보가 늘면 프롬프트가 길어진다. 후보 상한 5(`time_nearby_limit`)가
  그 방어다. 상한이 20을 넘으면 프롬프트 캐시 프리픽스 밖으로 밀린다.
- **LLM이 추가 조회를 요청할 수 없다.** "이 후보는 도크가 몇 개냐"를 되물을 수 없고, 프리페치가 넣어준
  값으로만 판단한다. 필요한 값이 빠지면 규칙 쪽에서 프리페치를 고쳐야 한다 — LLM이 스스로 보완하지
  못하는 것이 **설계상 의도**다(값을 지어내지 않게).
- **①②③이 틀리면 LLM이 고칠 수 없다.** 트리거가 잘못 울리면 LLM은 잘못 울린 상황에서 최선의 후보를
  고른다. 이건 결함이 아니라 책임 분리다 — 트리거 오류는 트리거 테스트가 잡는다.

### 1.4 그래프로 옮겨야 하는 조건

아래 중 하나가 생기면 이 절을 다시 쓴다.

1. **도구 선택이 결과에 의존**하게 될 때 — 예: ② 수단 변경에서 `replan` 결과의 leg를 보고 다시
   `nearby`를 불러야 하는 경우. 지금 ①(대여소 교체)에서는 없다.
2. **후보 수가 프롬프트 한 장에 안 들어갈 때** — 상한 5를 넘겨야 할 이유가 생기면.
3. **다중 목적 판단** — 재고·혼잡·소요를 사용자 선호에 따라 다르게 가중해야 하고, 그 선호를 대화로
   알아내야 할 때. 지금은 규칙 점수(`RuleStrategy.score`) 하나다.

이 조건이 생기기 전에 프레임워크를 넣으면 **1.2절의 다섯 축을 전부 잃고 얻는 것이 없다.**

### 1.5 이 판정이 코드에 어떻게 박혀 있나

- `planner.py` 모듈 docstring — "LLM에 넘기기 전에 필요한 조회를 여기서 다 끝낸다"
- `strategy.py` 모듈 docstring — "여기가 LLM을 갈아끼우는 유일한 자리"
- `AgentStrategy`는 `chosen_index`·`reason`만 받는다. 도구 호출 인자를 받는 자리가 없다 —
  그래프로 옮기려면 이 인터페이스부터 바꿔야 하므로, **실수로 LLM에 전이를 맡기게 되는 일은 없다.**

---

## 2. 재고 고갈 트리거·주변 대여소 후보 (S15P21A104-203)

### 2.1 왜 혼잡도에서 따릉이 재고로 바꿨나

CROWD는 **하루 1회 배치**(D-1) 산출물이다 — 실시간 신호가 아니라서, 이동 중 트리거로 쓰면
"어제 기준으로 혼잡할 것 같다"만 말할 수 있고 "지금 이 대여소가 비었다"는 말할 수 없다. 따릉이는
Kafka `bike.stock` 토픽으로 **120초 주기 스냅샷**이 들어온다(`FROM_BE-bike-stock-data-01` 회신
2번) — 트리거가 반응할 만한 실시간성이 여기 있다.

에이전트가 존재하는 이유는 이 시간차 하나다 — **"경로 탐색 시점엔 자전거가 있었는데, 걸어서
도착하니 없다."** ETA만큼 미래를 내다보고 그 간극을 메우는 것이 트리거의 일이지, 지금 비어
있는 대여소를 알려주는 것(그건 `bike_stations_nearby`의 `availableBikes` 하나로 충분하다)이
아니다.

### 2.2 트리거 7규칙

`trigger.evaluate()`(`trigger.py`)는 **먼저 맞는 규칙이 이긴다** — 오류(1)·모름(2)·신뢰 불가(3)를
먼저 걸러낸 뒤에만 "비었다"(6)를 판정한다. 값 안 지어내기 원칙이 순서 자체에 박혀 있다.

| # | 규칙 | reason | 뜻 |
| --- | --- | --- | --- |
| 1 | `stock_unknown` | `REASON_STOCK_UNKNOWN` | 도구가 `ToolError`. "물어보지 못했다"를 "비었다"로 읽지 않는다 |
| 2 | `horizon_out_of_range` | `REASON_HORIZON_OUT_OF_RANGE` | ETA가 `max_eta_min` 초과 또는 `model_horizon_min` 없음 |
| 3 | `low_confidence` | `REASON_LOW_CONFIDENCE` | `source == "lightgbm_global_fallback"`(신규 대여소, 전역 평균) |
| 4 | `cooldown` | `REASON_COOLDOWN` | 같은 이동에서 팝업 반복 방지 |
| 5 | `forced` | `REASON_FORCED` | `force_trigger=True`(dev 전용). 1~4는 그대로 지킨다 — 강제 트리거라도 값을 지어내진 않는다 |
| 6 | `p_empty` / `low_predicted_stock` | `REASON_P_EMPTY` / `REASON_LOW_PREDICTED_STOCK` | `p_empty ≥ time_trigger_p_empty` 임계 우선, 없으면 `predicted_stock ≤ time_trigger_min_stock` 폴백. `None`은 0이 아니다 |
| 7 | `below_threshold` | `REASON_BELOW_THRESHOLD` | 나머지 전부 — 평소 상태 |

노브는 `Thresholds`(`trigger.py`)가 `Settings`에서 읽는다.

| 노브 | 값 | 비고 |
| --- | --- | --- |
| `time_trigger_p_empty` | 0.7 | 도착 슬롯 0대 확률 상한 |
| `time_trigger_min_stock` | 1.0 | `p_empty` 없을 때 폴백 신호(예측 재고 하한) |
| `time_trigger_max_eta_min` | 30 | 학습 horizon(5·10·15·30) 밖은 근거로 안 쓴다 |
| `time_trigger_cooldown_sec` | 600 | 같은 이동 재발화 억제 |

넷 다 **잠정값**이다(`config.py` 주석) — 실제 재고·`p_empty` 분포를 보지 못한 채 데모를 위해
우선 박아둔 값이라, 데모 이후 실측으로 다시 정한다. 노브가 바뀌어도 판정 함수의 시그니처와
응답 API 모양은 그대로다 — 숫자만 흔들리는 자리를 `Settings`로 분리해둔 이유다.

### 2.3 주변 탐색을 BE `bike_stations_nearby`가 아니라 로컬 색인으로 하는 이유

`station_index.py`가 `latest_stock.parquet`(Kafka `bike.stock` 컨슈머가 station별 upsert로
유지하는 최신 스냅샷, `BIKE_LATEST_STOCK_COLUMNS` 7컬럼 — `rental_id`·`current_stock`·
`updated_at`·`station_name`·`lat`·`lng`·`rack_count`)를 읽어 haversine으로 주변을 훑는다.

이유는 둘이다.

1. **판정과 후보 생성이 한 원천이어야 한다.** 트리거(`get_eta_stock`)가 근거로 삼는 표와 후보
   탐색이 보는 표가 다르면 "후보로는 보이는데 재고 조회는 안 된다" 같은 어긋남이 생긴다.
2. **BE `bike_stations_nearby` DTO에는 판정에 쓸 재고 필드가 없다.** 도구 계약 1.1.0(`registry.py`)의
   출력 스키마는 `availableBikes`·`stockUpdatedAt`을 갖고 있다고 적었지만, 실제 BE DTO를 확인한
   결과(계획 v2 1절) `rentalId, name, lat, lng, dockCount, distanceMeters` **뿐**이다 — 그 전제가
   틀렸다는 것을 숨기지 않고 적는다. 정정은 `TOOL_CONTRACT.md`에, 다음 스키마 판 올릴 때 반영한다.

645곳 규모의 대여소 목록을 매 요청마다 haversine으로 훑는 비용은 ms 단위다 — 별도 공간 색인
없이 순수 파이썬 반복으로 충분하다.

### 2.4 후보 규칙

`candidates.generate()`(`candidates.py`)가 `station_index.nearby()` 결과를 가공한다.

- 반경 `time_nearby_radius_m` = 500m, 상한 `time_nearby_limit` = 5(`candidates.MAX_CANDIDATES`와
  같은 값)
- 대상 대여소 자기 자신 제외
- `current_stock == 0`(확실히 비었다고 알려진 대여소) 제외
- `current_stock is None`(모른다)은 **통과** — "모른다"를 "비었다"로 읽지 않는다
- `index.nearby(..., limit * 3 + 1)`로 상한보다 넉넉한 창을 먼저 받는다 — 반경 안에 재고 0인
  대여소가 여럿이면 제외 후 상한에 못 미칠 수 있어서다. `*3`은 근거가 강한 숫자가 아니라
  haversine 정렬이 싸다는 것만 믿고 잡은 여유값이다.

### 2.5 점수식과 LLM 생략

`RuleStrategy.score`(`strategy.py`)는

```
distance_m / 67 + p_empty × time_score_empty_penalty_min(10)
```

로 계산한다(작을수록 좋다). `67`은 `station_index.WALK_SPEED_M_PER_MIN`(분당 도보 속도, m) —
`build_walk_leg`가 실제 `walkLeg`를 합성할 때 쓰는 속도와 같은 상수를 순위 계산에도 써서, 후보
순위와 사용자에게 보여줄 도보 분(分)이 어긋나지 않게 한다. `time_score_empty_penalty_min`(10)은
p_empty가 1(=100% 확률로 빈다)이면 도보 10분 거리만큼 불리하게 보는 가중치다. 둘 다 **잠정값** —
실제 후보 분포를 보지 못했다.

`p_empty`가 없으면(분류기 미탑재 응답) `predicted_stock`으로 거친 근사를 쓴다(`_p_empty_or_proxy`):
예측 재고가 1대 이하면 1.0(거의 확실히 빈다), 그 밖이면 0.0(비지 않을 것). `predicted_stock`마저
없으면 그 후보는 점수를 매기지 않는다(값을 지어내지 않는다).

후보가 1개면 `AgentStrategy`도 LLM을 부르지 않고 `RuleStrategy`로 바로 넘긴다(`AgentStrategy.decide`)
— 고를 게 없는데 LLM을 부르는 것은 낭비고, 탈락으로 세면 204 평가에 "판단을 못 했다"는 잘못된
신호가 섞인다.

**331** — 에이전트 프롬프트(`strategy._system_prompt`)에 규칙과 같은 방향의 선택 기준을
명시했다("비어 있을 확률 낮은 후보 우선, 비슷하면 가까운 후보"). 기준 부재가 real 실행에서
LLM이 규칙과 다른 후보를 고른 원인이었다(`RESULTS.md` real 절).

### 2.6 새벽 07시 이전 미제공

Kafka `bike.stock` 수집 창은 **07:00~24:00**뿐이다(`FROM_BE-bike-stock-data-01`). 그 밖
(00:00~07:00)에는 `latest_stock.parquet`의 `updated_at`이 300초 신선도 기준
(`ParquetStationIndex.DEFAULT_MAX_STALENESS_SECONDS`)을 넘겨 `current_stock`이 전부 `None`이
되고, 트리거는 오류(1)나 신뢰 불가 판정으로 빠져 결국 `unavailable`이 된다. FE는 이 시간대에
그대로 조용히 무시하면 된다(`TO_FE-bike-reroute-04.md` 3절).

실질적인 공백 구간은 **첫차(05:30 전후)~07:00**다 — 수집이 아예 안 되는 00~07시와 달리, 이
구간은 사람은 이미 움직이는데 데이터가 없다. 이 구간 확장 여부는 원빈에게 물어 둔 상태다
(계획 3.2절).

## 3. 진입점 — `service.py` (S15P21A104-302)

`propose_reroute()` 하나가 ①~⑥을 잇는다(②재고 조회·⑥경로 연결·도보 합성이 302에서 추가됐다).
**순수 라이브러리다** — FastAPI·세션 보관소·HTTP 모양을 모른다. 호출 방향(FE→BE→AI / FE→AI)이
아직 결정 대기라(`FROM_BE-time-reroute-contract-01` 6번) 그 결정이 바뀌어도 이 파일이 안
바뀌게 하려는 것이고, `router.py`가 그 껍데기를 맡는다.

### 3.1 결과를 네 상태로 나눈다

| 상태 | 뜻 | 호출자가 할 일 |
| --- | --- | --- |
| `no_trigger` | 평소. 대부분의 폴링이 여기서 끝난다 | 아무것도 안 한다 |
| `no_alternative` | 트리거는 섰는데 갈아탈 대여소가 **실제로 없다** | 기존 안내 유지 |
| `unavailable` | 조회·판정을 **끝내지 못했다** | 조용히 무시 |
| `proposal` | 추천 있음 | 팝업 |

가운데 둘을 나누는 것이 이 모듈의 핵심 판단이다. `ToolErrorCode`의
`NOT_FOUND`/`UPSTREAM_UNAVAILABLE` 구분(`TOOL_CONTRACT.md` 2.1절)을 파이프라인 층으로 올린
것으로, **뭉개면 조회 장애가 "이 경로가 최선입니다"로 사용자에게 전달된다.**

`service.py` 모듈 docstring의 단계별 실패 매핑 표를 그대로 옮긴다 — 코드와 문서가 따로 놀지
않도록 이 표가 원본이다.

| 단계 | 조건 | 상태 | `reason` |
| --- | --- | --- | --- |
| ① 대상 조회 | `station_index.get(rental_id)`가 `None` | `UNAVAILABLE` | `target_unknown` |
| ③ 트리거 | `trig.reason == stock_unknown`(② 조회가 `ToolError`) | `UNAVAILABLE` | `stock_unknown` |
| ③ 트리거 | 그 밖의 미발화 사유(`below_threshold`·`cooldown`·`horizon_out_of_range`·`low_confidence`) | `NO_TRIGGER` | `trig.reason` 그대로 |
| ④ 후보 생성 | `candidates.generate()`가 빈 목록 | `NO_ALTERNATIVE` | `no_nearby_station` |
| ⑤ 프리페치 | 후보는 있는데 전부 조회 실패(`error is not None`) | `UNAVAILABLE` | `all_candidates_failed` |
| ⑤ 프리페치 | 전부 실패는 아닌데 `ctx.has_alternative`가 `False`(방어적 — 현재 `prefetch` 구현에서는 도달하지 않는다) | `NO_ALTERNATIVE` | `no_alternative` |
| ⑤ 선택 | `strategy`가 `None` | `UNAVAILABLE` | `no_strategy` |
| ⑤ 선택 | `strategy.decide(ctx)`가 `None`("대안은 있는데 점수를 못 냈다" — 대안 없음의 근거가 아니다) | `UNAVAILABLE` | `strategy_undecided` |
| ⑥ 경로 연결 | `boundary`가 `None` | `UNAVAILABLE` | `boundary_missing` |
| ⑥ 경로 연결 | `REPLAN_ROUTE`가 `ToolError` 또는 빈 배열(`route: null` 제안은 FE 결정상 금지) | `UNAVAILABLE` | `route_unavailable` |
| ⑥ 경로 연결 | 첫 원소에 안쪽 `route` dict가 없다 | `UNAVAILABLE` | `route_malformed` |
| ⑥ 성공 | 도보 합성까지 끝남 | `PROPOSAL` | `proposal.reason`(사용자 문장) |
| 그 외 | 어디서든 예상 못 한 예외 | `UNAVAILABLE` | `internal_error` |

### 3.2 상태를 갖지 않는다

`station_index`·`adapter`·`guard`·`strategy`·`seconds_since_last_fire`가 전부 **인자**다.
모두 세션(요청 하나 또는 한 이동) 단위로 살아야 하는 것이라 모듈이 들고 있으면 동시 사용자끼리
색인·예산·쿨다운을 나눠 쓴다(`TOOL_CONTRACT.md` 5절). 세션 보관소는 `session.py`의
`InMemorySessionStore`(계획 2.7절 `SessionStore` Protocol의 구현)가 맡는다 — 프로세스 내 TTL
dict라 **파드 1개를 전제**한다. 파드를 늘리면 사용자가 다른 파드로 라우팅될 때 쿨다운·세션이
끊기므로, 그 시점이 Redis로 바꿀 자리다.

전략을 주입받는 것은 204 비교의 전제이기도 하다 — 같은 파이프라인에 `RuleStrategy`와
`AgentStrategy`를 번갈아 태울 수 있어야 입력이 같다는 것이 구조로 보장된다
(`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번).

### 3.3 예외를 밖으로 내보내지 않는다

재안내는 "있으면 좋은 것"이다. 어댑터·가드는 이미 실패를 값으로 내지만(`TOOL_CONTRACT.md` 2절),
전략 구현이나 호출자가 넘긴 자료구조에서 새 예외가 날 수 있어 `propose_reroute()`가 `_propose()`
전체를 감싸 마지막 그물을 친다 — 재안내 하나 때문에 폴링 요청 전체가 500이 되는 일은 없어야
한다. 예외 detail은 로그에 남기지 않고 타입 이름만 남긴다 — `rental_id`·좌표 같은 사용자 이동
정보가 메시지에 섞여 있을 수 있어서다(`TOOL_CONTRACT.md` 5.2절과 같은 원칙).

### 3.4 ⑥ 경로 연결·도보 합성

선택된 대안이 정해지면(④⑤) 딱 한 번 `replan_route`를 부른다.

```
replan_route(step, boundary_id=대안.rental_id, dest_station_id)
```

`step`·`dest_station_id`는 호출자가 넘긴 값 그대로고, `boundary_id`만 원래 경계 대신 **선택된
대안 대여소의 `rental_id`**로 바꿔 부른다 — "여기서부터는 이 대여소를 거쳐 다시 탐색해 달라"는
뜻이다. 실패(`ToolError`)·빈 배열은 모두 `unavailable`(`route_unavailable`)이지 `route: null`
제안이 아니다 — FE가 명시적으로 거절했다(`TO_FE-bike-reroute-04.md` 회신, `route: null`을
경유 강제 없이 받을 수 없다는 이유). 첫 원소에 안쪽 `route` dict가 없으면(`route_malformed`)도
같은 이유로 제안을 내지 않는다.

`build_walk_leg(boundary, station)`(`service.py`)가 하차역(`boundary`)→대안 대여소 도보를
합성한다. BE `RouteLegResponse`와 같은 필드 이름(`mode/fromNodeId/fromNodeName/fromLat/fromLng/
toNodeId/toNodeName/toLat/toLng/routeId/routeName/minutes/distanceMeters/geometry/
geometryStatus`)에 `estimated: true`를 더한 모양이다 — FE가 같은 변환기를 그대로 타게 하려는
것(`TO_FE-bike-reroute-04.md` 2.2절). 계산:

- `WALK_DETOUR_FACTOR = 1.3` — 직선거리(`haversine_m`) → 실제 보행거리 근사 보정 계수. **잠정값**
- `WALK_SPEED_M_PER_MIN = 67`(`station_index.py`) — `distanceMeters / 67`이 `minutes`
- `geometry`는 GeoJSON `MultiLineString`, 좌표 순서 `[lng, lat]`(BE와 동일)
- `geometryStatus: "estimated"` — `"available"/"unavailable"`이 아니라 별도 값으로 "추정 도보"임을
  명시한다

**한계.** BE `BikeStockGate`(`domain/route/bike/BikeStockGate.java`)는 예측 맵이 비어 있으면
"원천 없음"으로 보고 기본 허용한다 — AI가 이 `replan_route` 호출에 예측 재고를 함께 넘기지
않으므로 게이트가 사실상 꺼져 있는 것과 같고, 하차역에서 BE가 재탐색하면 고갈이 확인된 원래
대여소를 다시 고를 수 있다. 그래서 `boundary_id`를 대안 대여소로 명시적으로 바꿔 부른다.

**첫 leg 검증(324).** BE 회신(`FROM_BE-bike-reroute-route-02.md` 1번, dev BE 수동 확인 대기가
이걸로 끝났다) — `boundaryId`=대여소여도 첫 leg BIKE는 보장이 아니다. 경계 대여소에서 도보가
더 싸면 WALK가 먼저 나오고, 옆 역이면 **WALK 단독**(prod 실측 `ST-1882→1024`)이다. 그래서
`service._pick_route_from_alternative`가 `replan_result` 전체에서 첫 leg가 BIKE·대안 출발인
첫 경로를 골라 쓰고, 없으면 재호출 없이 `unavailable`(`route_not_from_alternative`)이다.

### 3.5 API — `POST /time/reroute/check`

요청/응답 모델은 `api_schemas.py`(도메인 규약상 `schemas.py`는 도구 계층 공통 타입이 이미
점유하고 있어 이름을 피했다 — 3.6절). 계약 원문은 `TO_FE-bike-reroute-04.md`다 — 여기는 요약만
적고, 실제 필드 모양이 어긋나면 그 문서가 맞다.

- **요청**: 지금 안내 중인 대여소(`rentalId`)·도착까지 남은 분(`etaToRentalMinutes`)·원본 legs
  인덱스(`step`)·목적지 역(`destStationId`)·경계(`boundary{legIndex,nodeId,lat,lng}`, 넷 중
  하나라도 없으면 FE가 호출 자체를 하지 않는다)·`debugForceTrigger`(dev 전용). 폴링 조건은
  FE 쪽 판단이다 — 현재 leg가 SUBWAY고 그 인덱스가 `boundary.legIndex`보다 작을 때만, 120초
  주기(재고 원천 주기와 동일, `TO_FE-bike-reroute-04.md` 3절).
- **응답**: `status`(3.1절 네 값) + `reason`. `proposal`이면 추가로 `recommendationId`·
  `validUntil`(10분)·`recommendedBy`(`ALGORITHM`|`AGENT`)·`target{rentalId,name,currentBikes,
  predictedStock,pEmpty,horizonMin}`·`alternative{rentalId,name,lat,lng,distanceMeters,
  currentBikes,predictedStock,pEmpty}`·`boundary`(요청 에코)·`walkLeg`(3.4절)·`route`(BE
  `replan_route` 응답 원소의 **안쪽 `route`만** — 바깥 `reason`·`source`는 버린다).

**`GET /time/meta`(324-2)** — FE 디버그·시연용 노브 조회. 키를 뺀 트리거·후보 노브 현재값,
`strategyKind`(`AGENT`|`ALGORITHM`)·`llmModel`·`llmConfigured`, `stationIndexSize`·
`snapshotAgeSec`(색인·스냅샷 없으면 `null`), `sessionBudget{maxCalls,maxTotalTokens}`. 운영
판정에는 쓰지 않는다 — 항상 `Settings`를 새로 읽고, 절대 500을 내지 않는다.

### 3.6 아직 없는 것

- Redis 세션(3.2절 — 지금은 `InMemorySessionStore`, 파드 1개 전제)
- 세션 단위 LLM 예산의 파드 간 공유 — 324-3에서 세션(`InMemorySessionStore`)에는 붙였지만
  (`llm_budget.LlmBudget`), 저장소 자체가 파드 1개 전제라 파드 간 공유는 여전히 없다
- 좌표 목적지(`destLat/Lng`) — 지금은 역 목적지만(BE `replan` 계약 제약)
- `modes` 전면 재탐색(② 수단 변경) — 지금은 ① 대여소 교체만
- 실제 보행 라우팅(`viaNodeId` 경유 강제) — 지금은 직선×1.3 추정(3.4절). BE 회신
  (`FROM_BE-bike-reroute-route-02.md` 6번): **가능·공수 소~중(1~2일, 테스트 포함)**, 방식은
  2단 탐색(경계→via 1개 + via→목적지 K=3) 후 엣지 열 병합. **이번 스프린트 아님.** 리스크로
  게이트 ON 시 강제 경유 대여소가 재고 0으로 탈락하는 상호작용을 꼽았다 — "강제 경유 대여소는
  재고 게이트를 면제할지" 정책 질문이 대기 중이다.
- 204 기준선 비교(`RuleStrategy` vs `AgentStrategy` 정식 비교) — 구조는 갖췄으나 수치를 재지
  않았다(1절)
- Ingress·CORS·인증 — FE 실연결 전까지 mock
