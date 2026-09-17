# 실시간 컨슈머 (S15P21A104-171)

> **진행 중.** Kafka → Redis 반영. 반영기·배선·왕복 IT 까지 돼 있고 **prod 배포는 아직이다.**
> 수집기(프로듀서) 쪽은 [collector.md](collector.md), 이벤트 계약은 [kafka.md](kafka.md) 5절.

컨슈머 그룹은 **`be-redis`** 다. AI Spark 용 **`ai-spark`** 와 따로 둔다 — 그룹이 같으면 카프카가 메시지를 나눠 줘서
한쪽이 받은 것을 다른 쪽이 못 받는다. 그룹이 다르면 같은 이벤트를 양쪽이 각자 처음부터 읽는다 ([kafka.md](kafka.md) 5절).

---

## 1. statnId 매핑

### 왜 필요한가

실시간 도착 이벤트의 `entity_id` 는 서울시 API 의 `statnId` 인데, 우리 `station.station_id` 와 **체계가 다르다.**

| | 서울역 | 역삼 |
| --- | --- | --- |
| API `statnId` | `1001000133` | `1002000222` |
| 우리 `station_id` | `150` | `222` |

2호선처럼 우연히 뒷자리가 맞는 노선도 있지만 1호선은 전혀 다르다. 산술로 못 맞춘다.
그런데 A 파트 그래프·DB·192 조회 API 가 전부 우리 역번호로 찾으므로, 매핑 없이 쓴 Redis 키는 **아무도 찾을 수 없다.**
그래서 대응표를 컨슈머가 가진다 ([kafka.md](kafka.md) 5절: "대응표는 Redis 반영 컨슈머(171)가 갖는다").

### 규칙 — (노선, 정규화한 역명)

`statnId` 자체로는 못 찾고, **역명만으로도 안 된다.** 동명이역이 있다.

| 역명 | 노선 | `station_id` |
| --- | --- | --- |
| 신촌 | 2호선 `1002` | `240` |
| 신촌 | 경의중앙선 `1063` | `1252` |
| 양평 | 5호선 `1005` | `2523` |
| 양평 | 경의중앙선 `1063` | `1217` |

그래서 `(subwayId, 정규화한 statnNm)` 두 개로 찾는다. API 의 `subwayId` 는 `station-ids.csv` 의 `codes` 앞자리(`line_id`)와 같은 체계다.
**1호선도 이 방식이면 붙는다** — 코드는 달라도 노선과 이름은 같기 때문이다. 1호선용 별도 표는 필요 없었다.

### 역명 정규화 두 단계

순서가 중요하다. **괄호를 먼저 벗기고, 그 다음 별칭을 본다.**

1. **끝에 붙은 괄호를 벗긴다** — 실시간 API 는 부역명을 괄호로 붙여 준다.
   `총신대입구(이수)` → `총신대입구`, `천호(풍납토성)` → `천호`, `신촌(경의중앙선)` → `신촌`.
   우리 표에는 괄호가 붙은 이름이 **하나도 없어서** 벗겨도 안전하다. 이름 가운데 있는 괄호는 건드리지 않는다.
2. **`station-aliases.csv` 를 본다** — 표기 자체가 다른 역.
   `서울역` → `서울`, `응암순환` → `응암`, `세종왕릉` → `세종대왕릉`, `4.19 민주묘지` → `4.19민주묘지`(공백 차이).

`응암순환(상선)` 이 순서가 필요한 이유다 — 괄호를 벗겨야 `응암순환` 이 되고, 거기서 별칭으로 `응암` 이 된다.

### 만드는 법 (외부 API 호출 0회)

이미 Kafka 에 쌓인 회차를 읽어서 만든다. **서울시 하루 1,000회 예산을 쓰지 않는다.**

```bash
# 1. prod 에서 회차 덤프 (수집 창 10:00-15:30 안에서. 약 2분, 3회차 6,500건)
MSYS_NO_PATHCONV=1 ssh a104 "sudo kubectl exec -n prod sts/kafka -- \
  /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic subway.arrival --max-messages 6500 --timeout-ms 180000" \
  > .claude/perf/raw/subway-dump-2026-09-16.jsonl

# 2. 표 생성. --out 없이 먼저 돌려 안 붙는 역을 눈으로 확인한 뒤 쓴다
node BE/scripts/data/statn-id-map-build.mjs \
  --dump .claude/perf/raw/subway-dump-2026-09-16.jsonl \
  --ids BE/src/main/resources/data/subway/conf/station-ids.csv \
  --aliases BE/src/main/resources/data/subway/conf/station-aliases.csv \
  --out BE/src/main/resources/data/subway/conf/statn-id-map.csv --report
```

산출물 `data/subway/conf/statn-id-map.csv` 는 **커밋되면 정본이다.** 생성 규칙은
`BE/scripts/data/lib/statn-id-map.mjs` 와 `test/statn-id-map.test.mjs`(17건) 에 고정돼 있고,
읽는 쪽은 `consume/StatnIdMap.java` 다.

### 결과 (2026-09-16 · 덤프 6,500건 · 3회차)

**680역 매핑 · 10역 미매핑.**

| 노선 | 역 | 노선 | 역 | 노선 | 역 |
| --- | --- | --- | --- | --- | --- |
| 1001 | 99 | 1006 | 39 | 1075 | 62 |
| 1002 | 51 | 1007 | 53 | 1077 | 16 |
| 1003 | 44 | 1008 | 24 | 1081 | 12 |
| 1004 | 48 | 1009 | 38 | 1092 | 13 |
| 1005 | 56 | 1063 | 55 | 1093 | 21 |
| | | 1065 | 14 | 1094 | 11 |
| | | 1067 | 24 | | |

**안 붙는 역 10개 — 이 역들은 Redis 에 올라가지 않는다.** 전부 우리 정적 표에 노선·구간이 아직 없는 역이라 171 범위 밖이다.

| `statnId` | 노선 | 역명 | 왜 |
| --- | --- | --- | --- |
| `1001080164` | `1001` | 지제 | 1호선 남쪽(평택) 구간 미적재. 우리 1호선은 북쪽 연천(1919)까지 |
| `1032000346` | `1032` | 운정중앙 | GTX-A. 노선 `1032` 자체가 우리 표에 없다 (113 에서 미적재로 남김) |
| `1032000347` | `1032` | 킨텍스 | 〃 |
| `1032000348` | `1032` | 대곡 | 〃 |
| `1032000350` | `1032` | 연신내 | 〃 — 역명은 표에 있으나 노선이 없다 |
| `1032000351` | `1032` | 서울 | 〃 |
| `1032000353` | `1032` | 수서 | 〃 |
| `1032000354` | `1032` | 성남 | 〃 |
| `1032000355` | `1032` | 구성 | 〃 |
| `1032000356` | `1032` | 동탄 | 〃 |

### 표를 다시 만들 때

- **`--out` 없이 먼저 돌린다.** 안 붙는 역 수가 위 10개보다 늘었으면 새 노선이 개통했거나 역명이 바뀐 것이다 —
  원인을 확인하기 전에 표를 덮어쓰지 않는다.
- 별칭을 더할 자리는 `station-aliases.csv` 다. 근거를 함께 적는다.
- 덤프는 `.claude/` 아래(Git 제외)에 둔다. 표만 커밋한다.

---

## 2. Redis 값

**세 가지 키를 쓴다.** 값은 JSON 객체이고, 시각은 전부 ISO-8601 + 오프셋(KST) · 밀리초 이하 절사다 — 이벤트 계약과 같은 규칙.

> 형식은 192(전우석, 실시간 도착 조회 API)와 **합의 대상**이다. 제안 문서를 보냈고 답을 받으면 여기를 정본으로 갱신한다.

### `subway:arrival:{station_id}` · TTL 180초

```json
{
  "station_id": "222",
  "station_name": "강남",
  "poll_run_at": "2026-09-16T10:31:00+09:00",
  "source_generated_at": "2026-09-16T10:30:52+09:00",
  "written_at": "2026-09-16T10:31:02.140+09:00",
  "trains": [
    { "line_id": "1002", "updn_line": "상행", "train_line_nm": "성수행 - 강남방면",
      "train_no": "2234", "train_sttus": "일반", "dest_station_nm": "성수",
      "barvl_sec": 120, "arvl_cd": "2", "arvl_msg2": "강남 출발", "arvl_msg3": "강남",
      "last_car_at": "0", "recptn_dt": "2026-09-16T10:30:52+09:00",
      "eta_at": null, "eta_source": "none" }
  ]
}
```

- **`station_id` 는 우리 역번호다.** API 의 `statnId` 가 아니다 (1절).
- **`station_name` 은 정본 표의 이름이다.** API 표기(`총신대입구(이수)` 같은 부역명 괄호)를 그대로 쓰지 않는다.
- **`arvl_cd`·`arvl_msg2`·`arvl_msg3` 는 원본 코드·문구 그대로**다. 우리가 해석해서 가공하지 않는다 — 코드값 의미는 검증된 표가 없다.
- **`eta_at` 은 아래 규칙으로 채운다** (S15P21A104-224). 못 채우면 null 이고, 읽는 쪽은 `arvl_msg2` 문구를 그대로 쓰면 된다.

### 도착예정시각 산출 (S15P21A104-224)

규칙과 비율은 2026-09-16 prod 덤프 6,500행(3회차) 실측이다. 우선순위 순으로 본다.

| # | 조건 | `eta_at` | `eta_source` | 비율 |
| --- | --- | --- | --- | --- |
| 1 | `barvl_sec > 0` | `recptn_dt + barvl_sec` | `barvl` | 38.7% |
| 2 | `arvl_msg3 == statnNm` | `recptn_dt` | `arrived` | 14.4% |
| 3 | 그 외 | `null` | `none` | 46.9% |

1·2 에 함께 걸리는 행이 204건 있다. 원천이 직접 준 잔여시간이 더 정확하므로 **1 이 우선**이다.

**`arvlCd` 로 가르면 안 된다.** 실측상 `arvlCd=1`(도착) 932건 중 153건이 실제로는 `[N]번째 전역` 이고,
`arvlCd=99`(운행중) 중 1,807건은 오히려 `barvlDt` 를 가지고 있다. 코드값이 위치를 대표하지 못한다.
대신 `arvlMsg3`(열차가 지금 있는 역)가 조회 대상 역과 같은지를 본다 — **원천 표기끼리** 비교한다.
우리 정본 역명은 부역명 괄호를 벗긴 것이라 `arvlMsg3` 와 표기가 다를 수 있다.

**커버리지.** 행 기준 53.1% 지만, 사용자가 보는 것은 역·방향별 "다음 열차" 라 체감은 더 높다 —
573곳 중 **421곳(73.5%)** 에서 최소 한 대는 시각이 나온다.

| 노선 | 커버 | 노선 | 커버 |
| --- | --- | --- | --- |
| 2·6·7·8·9호선 · 우이신설 | 100% | 4호선 | 68% |
| 5호선 | 94% | 1호선 | 54% |
| 3호선 | 91% | 코레일·민자 (경의중앙·수인분당·신분당·공항철도 등) | 35~47% |

코레일·민자 노선은 `barvlDt` 를 아예 주지 않는다 — 데이터 품질 문제가 아니라 **운영사별 제공 정책 차이**다.

**이상치 가드.** 계산 결과가 `written_at` 기준 **−5분 ~ +30분** 을 벗어나면 `null` + `none` 이다.
8호선에 `recptn_dt` 가 13시간 미래인 행이 실재한다. 과거를 −5분만 허용하는 것은 이미 지난 열차를 "곧 도착" 으로
보여주지 않기 위해서다(원천이 정보를 만든 뒤 우리가 받기까지 노선별로 26~100초 걸리므로 0 으로 두면 정상값까지 잘린다).
가드가 버린 건수는 회차 로그에 `WARN` 으로 남는다.

**시계 어긋남과는 겹치지 않는다.** `recptn_dt` 가 미래로 어긋나는 노선은 신분당선 하나뿐인데(median +153초)
신분당선은 `barvlDt` 가 100% 0 이라 규칙 1 에 들어오지 않는다. 규칙 1 에 들어오는 노선(2·5·6·7·9호선)은
전부 26~43초 과거로 정상이다.

**범위 밖.** `[N]번째 전역`(46.9%)의 구간 합산은 `edge_time` 조회가 필요하다. 컨슈머가 60초마다 3,000건에 대해
DB 를 뒤지면 처리 여유(초당 836건, 실부하 대비 17배)를 깎으므로 **192 가 요청 시점에 하는 편이 낫다** — 협의 후 별도 티켓.

---

### `subway:arrival:status` · TTL 없음

역별 키가 **없을 때** 그 이유를 가르는 키다. 하나뿐이다.

```json
{ "state": "ok", "last_poll_run_at": "2026-09-16T10:31:00+09:00", "window": "10:00-15:30",
  "updated_at": "2026-09-16T10:31:02.140+09:00" }
```

| 역별 키 | `state` | 읽는 쪽이 보여줄 것 |
| --- | --- | --- |
| 있음 | `ok` | 실시간 도착 정보 |
| 없음 | `ok` | 그 역에 정보 없음 (열차 없음·미수집 역) |
| 없음 | `outside_window` | 지금은 실시간 제공 시간이 아님 — **장애가 아니다** |
| 없음 | `stale` | 수집 지연 중 |

- `outside_window` 판정에 쓰는 창은 **수집기와 같은 값이어야 한다** (`consume.subway.window`). 다르면 정상인데 "지연" 이라고 하거나 그 반대가 된다.
- 창 안인데 회차가 3분(`ArrivalStatus.STALE_AFTER`) 넘게 없으면 `stale`. 창 안인데 회차가 **하나도 없어도** `stale` 이다 — `ok` 라고 하면 읽는 쪽이 "정보 없음" 으로 오해한다.

### `bike:stock:{rental_id}` · TTL 300초

```json
{ "rental_id": "ST-1577", "available": 6, "racks": 15,
  "ingested_at": "2026-09-16T10:30:12+09:00", "written_at": "2026-09-16T10:30:14.021+09:00" }
```

- 키 이름은 `CacheKeys.bikeStock()` 에 원래 있던 것 그대로다. 값 모양만 171 에서 정했다.
- 재고는 **숫자로** 준다. 원천은 문자열이지만 읽는 쪽이 파싱하게 두지 않는다.

### TTL 을 이렇게 잡은 이유

TTL 은 "마지막 성공 쓰기 뒤 이만큼 지나면 모름으로 간주" 라는 뜻이다. **수집 주기보다 길어야 한다** —
짧으면 수집이 멀쩡히 도는데도 회차 사이마다 키가 사라져 그만큼 서비스가 막힌다.

| | 수집 주기 | TTL | 근거 |
| --- | --- | --- | --- |
| 따릉이 | 120초 | **300초** | 한 회차 놓침(120) + 서킷 브레이커(60) + 여유. 두 회차 연속 놓치면 만료 |
| 지하철 | 60초 | **180초** | 같은 규칙 |

따릉이는 61 에서 90초로 잡혀 있었다. 주기(120초)보다 짧아 **매 회차 30초씩 키가 없는** 상태였다 —
`cache/strategy.md` 가 "정확한 TTL 값은 스트림 갱신 주기가 정해지면 다시 조정한다" 고 해둔 그 조정을 171 에서 했다.

---

## 3. 실행

```bash
# 브로커·Redis·DB (컨텍스트를 공유하므로 DB 도 필요하다)
docker compose -f Infra/docker/docker-compose.yml up -d --wait kafka redis postgres

# 컨슈머
SPRING_PROFILES_ACTIVE=local,consume ./gradlew bootRun

# 브로커 없이 배선만 (Kafka 빈을 만들지 않는다)
SPRING_PROFILES_ACTIVE=local,consume ./gradlew bootRun --args='--consume.dry-run=true'
```

기본값은 `src/main/resources/application-consume.yml`. 환경변수 또는 `--consume.*` 로 덮는다.

| 환경변수 | 기본 | 뜻 |
| --- | --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | 브로커. 파드에서는 `kafka:9092` |
| `CONSUME_GROUP_ID` | `be-redis` | 컨슈머 그룹. **AI 의 `ai-spark` 와 달라야 한다** |
| `COLLECT_SUBWAY_WINDOW` | `07:30-13:00` | 상태 키 판정용. **수집기와 같은 값** |
| `REDIS_HOST` · `REDIS_PORT` | `localhost` · `6379` | |

명령행 전용: `--consume.dry-run=true` · `--consume.topics=subway.arrival` · `--consume.kafka.auto-offset-reset=earliest`.

**`weather.nowcast` 는 기본 구독에서 뺐다.** AI 가 Kafka 에서 직접 읽는지 확답을 못 받았고, 우리가 Redis 에 넣어도 읽는 쪽이 없다.
필요해지면 `consume.topics` 에 한 줄 더하고 반영기를 만든다.

---

## 4. 멱등과 보호 장치

| 장치 | 규칙 | 근거 |
| --- | --- | --- |
| 멱등 (지하철) | 저장된 `poll_run_at` 보다 **최신일 때만** 교체. 같은 회차면 이어붙이고, 옛 회차면 버린다 | NFR-STREAM-004 |
| 멱등 (따릉이) | 저장된 `ingested_at` 보다 **엄밀히 최신일 때만** 덮어쓴다. 같은 시각이면 중복이라 건너뛴다 | 〃 (따릉이는 생성 시각이 없다) |
| 역 단위 교체 | 새 회차는 그 역의 `trains` 를 통째로 바꾼다 | 열차별 부분 갱신이면 떠난 열차가 TTL 까지 남아 "탑승 확인" 을 오염시킨다 |
| 배치 경계 무관 | 회차가 여러 배치로 잘려 와도 결과가 같다 | 지하철 회차가 약 3,000건이라 `max-poll-records`(500)로 잘린다 |
| 오프셋 | `auto-offset-reset=latest`, 수동 커밋(`AckMode.BATCH`) | `earliest` 면 첫 기동에 보관 48시간치(약 290만 건)를 전부 재생한다 |
| 미매핑 역 | 쓰지 않고 센다 | 아무 역에나 쓰면 틀린 역의 도착 정보가 된다 |
| 깨진 레코드 | 그 건만 버리고 배치는 계속 | 한 건 때문에 회차 전체를 잃지 않는다 |
| 반영기 예외 | 잡아서 로그로 남기고 다음 토픽 계속 | 컨슈머가 죽으면 그때부터 전부 밀린다 (수집기 `SourcePoller.tick` 과 같은 하드 룰) |
| 동시성 | `concurrency=1` | 토픽이 전부 **파티션 1**(168). 2 이상으로 올려도 나머지는 논다 — 늘리려면 파티션부터 늘려야 한다 |

### 지연 측정

회차마다 로그에 두 구간을 남긴다. 어느 쪽이 늘어나는지로 병목이 Kafka 인지 우리 코드인지 갈린다.

```
ingested_at ──────→ 레코드 timestamp ──────→ written_at
     (produce 구간)          (consume 구간)
```

`min · median · p95 · max` 를 순위 기반으로 낸다 — [perf/README.md](../perf/README.md) 원칙 3 과 같은 정의다
(기존 기록이 n=5 라 p95 가 최댓값과 같은 것도 같은 규칙). 60초 주기라 며칠이면 표본이 저절로 쌓인다.

---

## 5. 검증

```bash
# 단위 (브로커·Redis 없이. 호출 0회)
./gradlew test --tests 'com.ssafy.s15p21a104.consume.*'

# 왕복 IT — 티켓 완료 기준 3건. 브로커·Redis·DB 가 떠 있어야 한다
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 ./gradlew test --tests '*ConsumerKafkaIT'

# 눈으로
docker exec -it sumgil-redis redis-cli --scan --pattern 'subway:arrival:*' | head
docker exec -it sumgil-redis redis-cli GET subway:arrival:status
docker exec -it sumgil-redis redis-cli TTL bike:stock:ST-1577
```

`ConsumerKafkaIT` 가 확인하는 것: 왕복 / 오래된 이벤트가 최신을 안 덮음 / TTL / statnId 변환 + 상태 키.

> TTL 만료는 300초를 기다릴 수 없어 둘로 나눠 본다 — (1) 컨슈머가 쓴 키에 TTL 이 실제로 걸렸는지,
> (2) 같은 값 모양을 1초 TTL 로 써서 Redis 가 지우는지. 둘을 합쳐 "갱신이 끊기면 키가 사라진다" 를 덮는다.

---

## 6. 보험 스위치 — Kafka 없이 돌리기

`collect.publisher` 로 수집기의 내보내기 경로를 바꾼다 (S15P21A104-171 티켓 본문 요구사항).

| 값 | 경로 | 쓸 때 |
| --- | --- | --- |
| `kafka` (기본) | 수집기 → Kafka → 컨슈머 → Redis | 평소 |
| `redis` | 수집기 → Redis (컨슈머와 **같은 반영기**를 직접 호출) | 브로커 장애로 발표 직전에 되돌려야 할 때 |

```bash
COLLECT_PUBLISHER=redis SPRING_PROFILES_ACTIVE=local,collect ./gradlew bootRun
```

`redis` 로 두면 **Kafka 빈을 아예 만들지 않는다** — 브로커가 없어도 기동한다. 반영 로직은 컨슈머와 같은 코드를 쓰므로
스위치를 돌려도 Redis 에 들어가는 값이 달라지지 않는다.

**잃는 것이 있다.** 이 경로에서는 AI 파트(`ai-spark` 그룹)가 **아무 이벤트도 받지 못하고**,
`weather.nowcast` 는 반영기가 없어 그냥 버려진다. 컨슈머가 죽어 있던 동안의 이벤트를 나중에 따라잡는 것도 안 된다.
그래서 기본값은 `kafka` 이고, `redis` 는 장애 때만 쓴다.

성능 비교는 [perf/2026-09-16-kafka-vs-direct.md](../perf/2026-09-16-kafka-vs-direct.md).

---

## 7. prod 배포

> **아직 배포하지 않았다.** `BE/k8s/` 는 플랫폼 소유라 적용 전에 리드 승인이 필요하다 (173 은 1회성 예외였다).
> 매니페스트는 작성·렌더링 확인까지 돼 있다.

| 파일 | 내용 |
| --- | --- |
| `k8s/prod/be-consumer.yaml` | Deployment. `sumgil-be:latest` 에 `SPRING_PROFILES_ACTIVE=prod,consume` |
| `k8s/prod/consumer.env` | `KAFKA_BOOTSTRAP_SERVERS`·`CONSUME_GROUP_ID` → `be-consumer-config` |
| `k8s/prod/kustomization.yaml` | 위 둘 등록 |

**설계 결정**

- **`replicas: 1` 고정.** 토픽이 전부 파티션 1이라 같은 그룹에 둘을 띄우면 하나만 일한다. `Recreate` 로 롤아웃 중 리밸런스가 두 번 일어나지 않게 한다.
- **`be-secret` 을 물리지 않는다.** 컨슈머는 외부 API 를 부르지 않는다 — Kafka 에서 읽어 Redis 에 쓰기만 하므로 인증키가 필요 없다.
- **`be-collector-config` 를 그대로 물린다.** 상태 키 판정에 쓰는 `COLLECT_SUBWAY_WINDOW` 가 수집기와 반드시 같아야 해서, 값을 복사하지 않고 같은 ConfigMap 을 쓴다.
- **프로브 없음.** HTTP 포트가 없다. 살아 있는지는 `kafka-consumer-groups` 의 LAG 로 본다.

**렌더링 확인 결과 (로컬).** 리소스 7개 → **9개** (`be-consumer` Deployment + `be-consumer-config` ConfigMap 추가).
`be-config` 해시가 그대로라 **`be` 파드는 재시작되지 않는다.**

절차는 [collector.md](collector.md) 8절과 같다 (동기화 → 렌더링 확인 → 빌드 → `apply.sh`).
`apply.sh` 는 `be`·`fe` 만 rollout 을 기다리므로 `be-consumer` 는 따로 친다.

```bash
ssh a104 'sudo kubectl rollout status deployment/be-consumer -n prod --timeout=180s'
```

**배포 후 검증**

```bash
# 키가 들어가는지
ssh a104 'sudo kubectl exec -n prod sts/redis -- redis-cli --scan --pattern "subway:arrival:*" | wc -l'
ssh a104 'sudo kubectl exec -n prod sts/redis -- redis-cli GET subway:arrival:status'

# 밀리지 않는지 — LAG 가 0 근처를 유지해야 한다
ssh a104 'sudo kubectl exec -n prod sts/kafka -- /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --group be-redis'

# 회차별 지연 (구간 두 개)
ssh a104 'sudo kubectl logs -n prod deployment/be-consumer --tail=20 | grep 배치'
```

---

## 8. 부하 시험

덤프를 재생해 백로그를 만든다. **외부 API 호출 0회**라 예산을 쓰지 않고 몇 번이든 돌릴 수 있다.

```bash
node BE/scripts/kafka/replay.mjs --dump .claude/perf/raw/subway-dump-2026-09-16.jsonl --times 17 --round \
  | docker exec -i sumgil-kafka /opt/kafka/bin/kafka-console-producer.sh \
      --bootstrap-server localhost:9092 --topic subway.arrival \
      --property parse.key=true --property key.separator=$'\t'

PERF=1 PERF_TOPIC=subway.arrival KAFKA_BOOTSTRAP_SERVERS=localhost:9092 REDIS_HOST=localhost \
./gradlew test --tests '*ConsumerBacklogIT' -i
```

**함정 둘.** 그냥 복제하면 아무것도 못 잰다 — 생성기가 회차마다 시각을 밀어 둘 다 피한다.

1. `event_id` 가 같으면 컨슈머 중복 제거가 전부 걸러낸다 → 처리량이 아니라 중복 제거 속도를 재게 된다
2. 시각이 그대로면 멱등 규칙("기존 값보다 최신일 때만")에 걸려 쓰기가 전부 스킵된다

**세 번째 함정.** 반영기는 **Kafka 토픽 이름**으로 고른다. `perf.backlog` 같은 임시 토픽에 쌓으면 전부 무시되고
루프 오버헤드만 재게 된다 (실제로 한 번 이렇게 쟀다). `ConsumerBacklogIT` 에 "Redis 쓰기가 0회면 실패" 가드를 넣어 뒀다.

**로컬 compose 에만 쏜다.** prod 에 쏘면 가짜 재고·도착이 실제 Redis 에 들어가고 AI 컨슈머도 그것을 먹는다.
실험 뒤에는 로컬 토픽을 지워 재생분을 남기지 않는다 (수집기·컨슈머가 기동할 때 다시 만든다).

```bash
docker exec sumgil-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --delete --topic subway.arrival
```

측정 결과는 [perf/2026-09-16-consumer-backlog.md](../perf/2026-09-16-consumer-backlog.md).

---

## 9. 적용 결과 (2026-09-16)

`be-consumer-65f4b5b755-6lvjb` · 기동 31.6초 · 롤아웃 성공.

**설정이 의도대로 물었다.**

```
컨슈머 — 그룹 be-redis · 토픽 [subway.arrival, bike.stock] · 오프셋 latest · 배치 최대 500건 · 브로커 kafka:9092
지하철 역 대응표 680건 · 운영 시간 창 10:00-15:30
```

창이 `10:00-15:30` 으로 찍혔다 — `be-collector-config` 를 물린 것이 동작했다는 뜻이다
(안 물렸으면 기본값 `07:30-13:00` 이 나와 13시대에 `outside_window` 로 오판했을 것이다).

**Flyway 가 V4 를 적용했다** — `Successfully applied 1 migration`. `FlywayConfig` 에 프로파일 제한이 없어
컨슈머 기동 때 마이그레이션이 돈다. 컨슈머를 올리면 DB 마이그레이션도 함께 간다는 뜻이니 알아둘 것.

**Redis · LAG (13:27 기준)**

| 확인 | 결과 |
| --- | --- |
| `subway:arrival:*` | 555키 (매핑표 680역 중. 최근 3분 안에 열차가 잡힌 역만 남는다 — TTL 180초) |
| `bike:stock:*` | 2,735키 (09-15 실측 2,738건과 사실상 같다 = 전 대여소) |
| `subway:arrival:status` | `{"state":"ok","last_poll_run_at":"...13:27:14+09:00","window":"10:00-15:30"}` |
| 컨슈머 그룹 LAG | `subway.arrival` 0 · `bike.stock` 0 |

### prod 지연 — 로컬에서 못 재던 구간

배치 로그에서 두 구간이 나왔다. 아래는 배포 당일 회차 몇 개를 눈으로 읽은 값이다.
**정식 기록은 [docs/perf/2026-09-16-consumer-prod-latency.md](../perf/2026-09-16-consumer-prod-latency.md) 를 본다** — 같은 날 38회차를
파싱해 워밍업을 빼고 median·p95 를 낸 것이라 규약 원칙 3 을 채운다. 인용은 그쪽에서 한다.

| 구간 | 값 | 읽는 법 |
| --- | --- | --- |
| **produce** (`ingested_at` → 레코드 timestamp) | median 41~188 ms | **Kafka 가 얹은 실제 비용.** 배치 안 편차가 2~4 ms 로 안정적이다. 로컬 벤치의 66 ms 와 자릿수가 맞는다 |
| **consume** (레코드 timestamp → `written_at`) | 7 ms → 4,500 ms 로 올랐다가 리셋 | **지연이 아니라 회차 소화 진행도다.** 한 회차(약 3,000건)가 배치 6~8개로 잘려 들어오는 동안 뒤쪽 배치가 기다린 시간이고, 새 회차가 오면 0 으로 돌아간다 |

**회차 하나를 다 소화하는 데 5~9초**로 보였다. 표본이 작아 그대로 인용하지 말 것 —
38회차를 파싱한 결과는 배수시간 median 2,831~3,471 ms · 초당 약 790~870건이다(위 정식 기록).
두 값의 차이는 표본 크기 차이지 개선이 아니다. 어느 쪽이든 주기 60초에 견줘 여유가 크다는 결론은 같다.

배치당 미매핑 2~10건은 **정상이다** — GTX-A 9역과 1호선 지제의 도착 정보가 회차마다 계속 들어오므로 매번 세어진다.

### 배포 때 밟은 것 — `be` server-side apply 충돌

`apply.sh` 가 `be` 에서 멈췄다.

```
error: Apply failed with 2 conflicts: conflicts with "kubectl-patch" using apps/v1:
- .spec.template.spec.containers[name="be"].envFrom
conflicts with "kubectl-set" using apps/v1:
- .spec.template.spec.containers[name="be"].image
```

누군가 `kubectl patch`·`kubectl set image` 로 `be` 를 git 밖에서 바꿔 둔 상태라 server-side apply 가 거부했다.
**우리 배포가 만든 문제가 아니고** `be-consumer`·`be-collector`·ConfigMap 은 모두 정상 적용됐다.
오히려 `be` 가 전혀 건드려지지 않아 의도대로였다.

다만 두 가지가 남는다.

- `set -euo pipefail` 이라 스크립트가 여기서 멈춰 **`fe` apply 와 rollout 대기가 실행되지 않았다.** `fe` 는 이미 돌던 그대로다.
- **git 과 prod 가 갈라져 있다.** 다음에 누가 `apply.sh` 를 돌려도 같은 곳에서 멈춘다.

`--force-conflicts` 는 쓰지 않았다 — 그 수동 패치의 이유를 모르는 상태에서 덮어쓰면 `be` 가 재시작되고
누군가의 의도를 되돌리게 된다. **플랫폼 담당이 정리할 문제로 넘긴다.**

---

## 10. 도착예정시각 배포 (2026-09-16 · S15P21A104-224)

`be-consumer-6f66f5f48b-rt6b6` · 롤아웃 성공.

**배포 방법이 171 때와 다르다.** 이번 변경은 k8s 매니페스트를 건드리지 않고 Java 코드만 바뀌었다.
그런데 Deployment 가 `image: sumgil-be:latest` 를 쓰므로 이미지를 새로 빌드해도 **spec 문자열이 그대로라
`kubectl apply` 로는 롤아웃이 일어나지 않는다.** 파드가 옛 코드로 계속 돈다.

```bash
# 1. 동기화
NODES=a104 bash Infra/k8s/scripts/sync-to-nodes.sh
# 2. 이미지 재빌드 (15~20분)
ssh a104 'cd ~/sumgil && nohup bash Infra/k8s/scripts/build-push.sh be > /tmp/build-be.log 2>&1 & echo started'
# 3. 이것이 실제 배포다
ssh a104 'sudo kubectl rollout restart deployment/be-consumer -n prod'
ssh a104 'sudo kubectl rollout status deployment/be-consumer -n prod --timeout=180s'
```

`apply.sh` 는 돌리지 않았다 — 매니페스트가 안 바뀌었고, 돌리면 `be` server-side apply 충돌(9절)에 걸려
그 뒤 `fe` 적용까지 막힌다. `be-collector` 도 같은 `latest` 를 쓰지만 재시작하지 않았다(수집기 코드는 안 바뀌었고
재시작하면 수집이 잠깐 끊긴다).

되돌리려면 `kubectl rollout undo deployment/be-consumer -n prod` 한 줄이다.

### 검증 결과 (강남역 15:23:11 회차)

| 노선 | 열차 | `barvl_sec` | `arvl_msg3` | `eta_at` | `eta_source` |
| --- | --- | --- | --- | --- | --- |
| 1002 | 3279 | 80 | 교대 | 15:24:03 | `barvl` |
| 1002 | 3276 | 60 | 역삼 | 15:23:43 | `barvl` |
| 1002 | 2278 | 240 | 삼성 | 15:26:27 | `barvl` |
| 1002 | 2281 | 270 | 방배 | 15:27:13 | `barvl` |
| 1077 | 9 · 12 · 20 | 0 | 논현·청계산입구·판교 | null | `none` |

**7대 중 4대에 도착시각이 붙었다.** 계산도 맞는다 — 회차 15:23:11 에 80초 남은 열차가 15:24:03 이다.
신분당선(1077) 3대는 `barvl_sec=0` 이고 `arvl_msg3` 가 강남이 아니라 규칙대로 `none` 이다.
실측에서 신분당선이 `barvlDt` 를 100% 주지 않는다고 나온 것과 일치한다.

배치 로그도 정상이었다 — `배치 500건 — 반영 500 · 건너뜀 0 · 미매핑 0 · 실패 0`, produce median 42ms.

### 가드가 실제로 걸린다

배포 직후 `도착예정시각 가드가 N건을 버렸다` WARN 이 **12회** 찍혔다. 8호선 같은 이상치가 실제로 걸러지고 있다는 뜻이다.
로그로 남긴 것이 제 역할을 했다 — 건수가 늘어나면 범위(−5분 ~ +30분) 조정을 검토한다.
