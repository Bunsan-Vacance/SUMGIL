# Redis 캐싱 전략 (S15P21A104-61)

> 키 네이밍·TTL 정책의 정본. 실시간 값을 **누가 채우는지**는 2026-09-16(S15P21A104-171)에 바뀌었다 —
> 아래 표와 "다음 Task" 절 참고. 실시간 값의 실제 모양은 [docs/infra/consumer.md](../infra/consumer.md) 2절.

`BE/README.md` 4절 데이터 흐름 기준으로, Redis에 올라가는 값은 성격이 다른 두 가지다. 이 문서는 그 둘의 키 네이밍·TTL 정책을 정한다.
61 시점에는 정책 확정 + Spring Data Redis 기본 연동(`RedisConfig`, `CacheKeys`, 읽기/쓰기 테스트)까지였고, **실시간 값을 실제로 채우는 로직은 S15P21A104-171 에서 구현했다**(`consume` 패키지).

## 두 종류

| 종류 | 원천 | 갱신 주체 | 성격 |
| --- | --- | --- | --- |
| 사전계산 결과 캐시 (예: 역전구간 판정) | **BE 경로 알고리즘**(전우석, `ROUTE-002`)이 요청 시 계산. `edge_time` 등 원본 데이터는 AI 배치 산출물(PostgreSQL)이지만, "역전구간인지" 판정 자체는 AI가 아니라 BE 코드가 한다 | BE가 조회 시 최초 계산해서 적재(cache-aside) — `S15P21A104-63` `search`가 이 흐름을 그대로 씀 (`BE/docs/api/route-api-spec.md` 참고) | 같은 역 쌍·시간대 요청이 반복되므로 캐시로 재계산 부하를 줄인다. 원본 데이터(Postgres)가 있으므로 만료돼도 다시 계산할 수 있다 |
| 실시간 값 (재고, 도착정보) | **C 파트 수집기**(`collect` 프로파일)가 서울시 API 를 폴링해 Kafka 로 보낸다 | **C 파트 컨슈머**(`consume` 프로파일, `be-redis` 그룹)가 Kafka 에서 꺼내 쓴다. A·B 는 read-only | **Redis가 유일한 저장소다.** 원본이 없어 만료되면 그 값은 "모름" 상태가 된다. `BE/README.md` 4절: "Redis가 죽으면 실시간 재고를 못 읽는다 → 자전거 추천 차단" |

## 키 네이밍 규칙

`{도메인}:{세부종류}:{자연키...}` — 소문자, 콜론(`:`) 구분. 자연키는 `BE/docs/db/schema.md`의 테이블 자연키(`station_id`, `rental_id` 등)를 그대로 쓴다. 새 종류를 추가할 필요가 있으면 이 표와 `CacheKeys`에 함께 추가한다.

| 캐시 | 키 형식 | 예시 | TTL |
| --- | --- | --- | --- |
| 역전구간 판정 결과 | `reversal:{originStationId}:{destStationId}:{dowType}:{timeSlot}` | `reversal:222:221:0:14` | 30분 |
| 따릉이 실시간 재고 | `bike:stock:{rentalId}` | `bike:stock:ST-1577` | 300초 |
| 지하철 실시간 도착 | `subway:arrival:{stationId}` | `subway:arrival:222` | 180초 |
| 지하철 수집 상태 | `subway:arrival:status` (하나뿐) | — | 없음 |

`dowType`·`timeSlot`은 `BE/docs/db/schema.md`와 동일하게 0=평일/1=토요일/2=일요일·공휴일, 30분 단위 슬롯(0~47)이다.

## TTL 근거

- **역전구간 판정(30분)** — `edge_time`/`congestion` 등 원본이 `dow_type`·`time_slot`(30분 슬롯) 단위로 갱신되므로, 캐시도 그 슬롯 하나만큼만 유효하면 된다. 그보다 길면 슬롯이 바뀌었는데 이전 슬롯 값을 내려줄 위험이 있고, 짧으면 캐시 효과가 없다.
- **실시간 재고(300초·2026-09-16 조정)** — 갱신이 멈춰도 오래된 숫자를 계속 내려주면 "헛걸음"을 유발한다(`BE/README.md` 4절). Redis는 재고 값의 **유일한** 저장소라서(원본이 없음), 갱신이 끊겨도 값 자체는 그대로 남아있을 수 있다 — TTL이 없으면 "6대 남음"이 몇 시간이 지나도 계속 조회된다. 그래서 TTL을 두어 **갱신이 끊기면 키가 자동으로 만료되어 "재고를 모름" 상태가 되도록** 설계했다.
  처음에는 90초로 잡았으나, 수집 주기가 120초로 확정되면서(S15P21A104-170) **TTL이 주기보다 짧아 매 회차 30초씩 키가 사라지는** 문제가 있었다.
  아래 원칙대로 300초로 조정했다(171) — 한 회차 놓침(120초) + 서킷 브레이커(60초) + 여유. 두 회차 연속 놓치면 만료되는 것이 의도다.
  지하철도 같은 규칙으로 60초 주기에 180초다. **TTL은 수집 주기보다 반드시 길어야 한다.** 이 키를 조회하는 쪽은 키가 없을 때를 "재고 0"이 아니라 "알 수 없음"으로 다뤄야 하며, 이 경우 자전거 추천을 하지 않고 `blockedReason`으로 사유를 내려야 한다. 지하철은 키 부재만으로 "정보 없음 / 운영창 밖 / 수집 지연"을 못 가르므로 `subway:arrival:status` 를 함께 본다 ([consumer.md](../infra/consumer.md) 2절).

## 기본 연동

- `global/config/RedisConfig`: `RedisTemplate<String, Object>` 빈. 키는 문자열, 값은 JSON(`GenericJacksonJsonRedisSerializer`)으로 직렬화한다 — Spring Boot 기본 템플릿(JDK 직렬화)은 다른 언어(Spark/Python)가 쓴 값을 못 읽으므로 쓰지 않는다.
- `global/cache/CacheKeys`: 위 표의 키 생성 메서드와 TTL 상수.
- `RedisConfigTest`: 실제 Redis에 JSON 값을 TTL과 함께 쓰고, 읽고, TTL이 설정됐는지, 지운 뒤 없어졌는지까지 확인한다. `.claude/skills/verify` 절차(Docker Desktop 켜고 `docker compose ... up -d postgres redis`)로 로컬 검증 가능하고, CI `be-test` job에도 이미 redis 서비스가 붙어 있어 그대로 통과한다.

## 다음 Task에서 할 일

1. ~~역전구간 판정 로직이 생기면 `CacheKeys.reversal(...)`로 조회하고, 없으면 계산해서 캐시에 채우는 cache-aside 서비스를 추가한다.~~ → `S15P21A104-63`에서 별도 `escape` 도메인이 아니라 `search`의 혼합 경로 후보 계산으로 흡수하기로 확정됨. `BE/docs/api/route-api-spec.md` 참고.
2. ~~Spark Streaming 쪽에서 `bike:stock:{rentalId}` 키로 실시간 재고를 쓰도록 연동한다.~~
   → **설계가 바뀌었다 (2026-09-16, S15P21A104-169·171).** Spark 가 Redis 에 직접 쓰지 않는다.
   C 파트 수집기가 서울시 API 를 폴링해 Kafka 로 보내고, C 파트 컨슈머(`be-redis` 그룹)가 꺼내 Redis 에 쓴다.
   AI Spark 는 **같은 Kafka 토픽을 `ai-spark` 그룹으로 따로 읽는다** — Redis 를 거치지 않는다
   ([kafka.md](../infra/kafka.md) 5절, [consumer.md](../infra/consumer.md)).
3. `bike:stock:{rentalId}` 조회 로직(자전거 추천 비교 로직)을 만들 때는 **키가 없는 경우를 "재고 0대"가 아니라 "알 수 없음"으로 처리**하고, 그 경우 자전거를 추천하지 않고 `blockedReason`으로 사유를 내려야 한다 — 위 TTL 근거 참고.
4. Notion 캐싱 전략 문서를 이 파일 기준으로 갱신한다 (Jira `S15P21A104-61` 완료 기준 항목).
