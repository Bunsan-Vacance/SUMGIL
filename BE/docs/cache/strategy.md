# Redis 캐싱 전략 (S15P21A104-61)

> 초기 구축 시점의 설계다. 변경될 수 있다.

`BE/README.md` 4절 데이터 흐름 기준으로, Redis에 올라가는 값은 성격이 다른 두 가지다. 이 문서는 그 둘의 키 네이밍·TTL 정책을 정한다. **실제로 값을 채우는 로직(사전계산 결과 적재, 스트림 갱신)은 이 작업 범위 밖이다** — 데이터 파이프라인(AI 배치, Spark Streaming) 연동 후 별도 Task에서 구현한다. 이번 작업은 정책 확정 + Spring Data Redis 기본 연동(`RedisConfig`, `CacheKeys`, 읽기/쓰기 테스트)까지다.

## 두 종류

| 종류 | 원천 | 갱신 주체 | 성격 |
| --- | --- | --- | --- |
| 사전계산 결과 캐시 (예: 역전구간 판정) | AI 배치 산출물 (PostgreSQL이 원본) | BE가 조회 시 최초 적재(cache-aside) 또는 배치가 직접 채움 — 방식은 파이프라인 연동 시 결정 | 같은 역 쌍·시간대 요청이 반복되므로 캐시로 DB 부하를 줄인다. 원본(Postgres)이 있으므로 만료돼도 다시 채울 수 있다 |
| 실시간 값 (재고, 도착정보) | Spark Streaming | 스트림이 직접 씀. BE는 read-only | **Redis가 유일한 저장소다.** 원본이 없어 만료되면 그 값은 "모름" 상태가 된다. `BE/README.md` 4절: "Redis가 죽으면 실시간 재고를 못 읽는다 → 자전거 추천 차단" |

## 키 네이밍 규칙

`{도메인}:{세부종류}:{자연키...}` — 소문자, 콜론(`:`) 구분. 자연키는 `BE/docs/db/schema.md`의 테이블 자연키(`station_id`, `rental_id` 등)를 그대로 쓴다. 새 종류를 추가할 필요가 있으면 이 표와 `CacheKeys`에 함께 추가한다.

| 캐시 | 키 형식 | 예시 | TTL |
| --- | --- | --- | --- |
| 역전구간 판정 결과 | `reversal:{originStationId}:{destStationId}:{dowType}:{timeSlot}` | `reversal:0222:0221:0:14` | 30분 |
| 따릉이 실시간 재고 | `bike:stock:{rentalId}` | `bike:stock:ST-1577` | 90초 |

`dowType`·`timeSlot`은 `BE/docs/db/schema.md`와 동일하게 0=평일/1=토요일/2=일요일·공휴일, 30분 단위 슬롯(0~47)이다.

## TTL 근거

- **역전구간 판정(30분)** — `edge_time`/`congestion` 등 원본이 `dow_type`·`time_slot`(30분 슬롯) 단위로 갱신되므로, 캐시도 그 슬롯 하나만큼만 유효하면 된다. 그보다 길면 슬롯이 바뀌었는데 이전 슬롯 값을 내려줄 위험이 있고, 짧으면 캐시 효과가 없다.
- **실시간 재고(90초)** — 스트림이 멈춰도 오래된 숫자를 계속 내려주면 "헛걸음"을 유발한다(`BE/README.md` 4절). Redis는 재고 값의 **유일한** 저장소라서(원본이 없음), 갱신이 끊겨도 값 자체는 그대로 남아있을 수 있다 — TTL이 없으면 "6대 남음"이 몇 시간이 지나도 계속 조회된다. 그래서 TTL을 스트림 갱신 주기보다 여유 있게 짧게(90초) 잡아, **갱신이 끊기면 키가 자동으로 만료되어 "재고를 모름" 상태가 되도록** 설계했다. 이 키를 조회하는 쪽(향후 escape 도메인)은 키가 없을 때를 "재고 0"이 아니라 "알 수 없음"으로 다뤄야 하며, 이 경우 자전거 추천을 하지 않고 `blockedReason`으로 사유를 내려야 한다 — 아직 그 조회 로직 자체는 없고(2절 "실제 캐시 갱신 로직은 범위 밖"), 이 TTL 정책은 그 로직이 지켜야 할 계약이다. 정확한 TTL 값은 스트림 갱신 주기가 정해지면 다시 조정한다.

## 기본 연동

- `global/config/RedisConfig`: `RedisTemplate<String, Object>` 빈. 키는 문자열, 값은 JSON(`GenericJacksonJsonRedisSerializer`)으로 직렬화한다 — Spring Boot 기본 템플릿(JDK 직렬화)은 다른 언어(Spark/Python)가 쓴 값을 못 읽으므로 쓰지 않는다.
- `global/cache/CacheKeys`: 위 표의 키 생성 메서드와 TTL 상수.
- `RedisConfigTest`: 실제 Redis에 JSON 값을 TTL과 함께 쓰고, 읽고, TTL이 설정됐는지, 지운 뒤 없어졌는지까지 확인한다. `.claude/skills/verify` 절차(Docker Desktop 켜고 `docker compose ... up -d postgres redis`)로 로컬 검증 가능하고, CI `be-test` job에도 이미 redis 서비스가 붙어 있어 그대로 통과한다.

## 다음 Task에서 할 일

1. 역전구간 판정 로직(escape 도메인)이 생기면 `CacheKeys.reversal(...)`로 조회하고, 없으면 Postgres에서 읽어 캐시에 채우는 cache-aside 서비스를 추가한다.
2. Spark Streaming 쪽에서 `bike:stock:{rentalId}` 키로 실시간 재고를 쓰도록 연동한다 (BE는 읽기만 한다 — `BE/README.md` 9절 "외부 API를 BE가 직접 폴링하지 않는다").
3. `bike:stock:{rentalId}` 조회 로직(자전거 추천 비교 로직)을 만들 때는 **키가 없는 경우를 "재고 0대"가 아니라 "알 수 없음"으로 처리**하고, 그 경우 자전거를 추천하지 않고 `blockedReason`으로 사유를 내려야 한다 — 위 TTL 근거 참고.
4. Notion 캐싱 전략 문서를 이 파일 기준으로 갱신한다 (Jira `S15P21A104-61` 완료 기준 항목).
