# 실시간 수집기 (S15P21A104-169 · 170)

외부 API 3종을 주기 폴링해 Kafka 토픽 3개에 넣는 프로듀서다. BE 앱의 **`collect` 프로파일**로 돈다 —
`load` 프로파일(정적 적재)과 같은 방식으로, 웹 서버를 띄우지 않고 러너만 실행한다.
토픽·보관 정책·이벤트 계약은 [kafka.md](kafka.md) 4·5절이 정본이고, 이 문서는 **수집기를 돌리고 설정하는 법**을 다룬다.

```
[서울시 지하철 도착 API] ─┐                       ┌─▶ subway.arrival ─┐
[따릉이 bikeList API]    ─┼─▶ 수집기(collect) ──▶ Kafka ─┼─▶ bike.stock ────┼─▶ 컨슈머 be-redis (171) → Redis
[기상청 API허브]         ─┘   주기 · 시간 창 · 예산      └─▶ weather.nowcast ┘   컨슈머 ai-spark (AI)   → parquet
```

## 1. 실행

```bash
# 저장소 루트에서 — 브로커·DB·Redis (컨텍스트를 공유하므로 DB·Redis 도 필요하다)
docker compose -f Infra/docker/docker-compose.yml up -d --wait kafka postgres redis

cd BE
export DB_URL=jdbc:postgresql://localhost:5432/sumgil DB_USERNAME=sumgil DB_PASSWORD=sumgil1234 REDIS_HOST=localhost REDIS_PORT=6379
# 인증키·KAFKA_BOOTSTRAP_SERVERS 는 BE/.env (bootRun 전용 dotenv). 키 이름은 BE/.env.example

# 주기 실행 (Ctrl+C 로 종료)
SPRING_PROFILES_ACTIVE=local,collect ./gradlew bootRun

# 한 회차만 돌리고 종료 — 배포 전 점검·스키마 확인
SPRING_PROFILES_ACTIVE=local,collect ./gradlew bootRun --args='--collect.run-once=true'

# 브로커 없이 호출·파싱만 (Kafka 빈을 만들지 않는다) — 첫 이벤트 JSON 이 로그에 찍힌다
SPRING_PROFILES_ACTIVE=local,collect ./gradlew bootRun --args='--collect.run-once=true --collect.dry-run=true'

# 소스 골라 끄기 (실습실 망에서는 bikeList 가 막혀 있다 — api-survey.md 3절)
SPRING_PROFILES_ACTIVE=local,collect ./gradlew bootRun --args='--collect.bike.enabled=false --collect.weather.enabled=false'
```

기동하면 소스별 계획을 한 줄씩 찍고, 회차마다 요약을 남긴다.

```
subway.arrival — 주기 60s · 창 07:30-13:00 · 회차당 3회 · 하루 계획 990회 / 예산 1000회
subway.arrival 운영 시간 창 07:30-13:00 — 지금 안 (11:50:21)
subway.arrival 회차 2026-09-14T11:50:21+09:00 — 호출 3회 · 행 3002건 · 전송 3002건 · 963ms · 오늘 호출 3/1000
```

계획이 예산을 넘으면 `⚠ 계획이 예산을 넘는다` 가 붙는다. 창 밖으로 나가고 들어올 때, 서킷이 열릴 때, 예산이 다 찼을 때만 추가 로그가 난다.
회차 로그의 `traceId` 는 `소스@회차시각` 이다.

## 2. 소스

| 토픽 | 원천 | 호출 | 주기 · 창(기본) | `entity_id` | `source_generated_at` | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| `subway.arrival` | 지하철 실시간 도착 일괄 OA-15799 `swopenapi.seoul.go.kr/api/subway/{KEY}/json/realtimeStationArrival/{start}/{end}/ALL` | 1,000행씩 이어 받고 `total` 에 닿으면 끝. 보통 3회, `total` > 3,000 이면 4회(상한) | 60초 · 07:30-13:00 | `statnId` (API 고유 ID, 예 `1009000937`) | `recptnDt` | **실측 2026-09-14 11:50** — 3회 · 3,002행 · 963ms, `total` 3,009. 로컬 Kafka 에 적재 확인 |
| `bike.stock` | 따릉이 bikeList OA-15493 `openapi.seoul.go.kr:8088/{KEY}/json/bikeList/{start}/{end}/` | 1,000건씩 3회. 마지막 페이지가 1,000 미만이면 끝 | 120초 · 07:00-18:00 | `stationId` (`ST-xxx` = `bike_station.rental_id`) | 없음 → `null`, `ingested_at` 이 신선도 기준 | **실측 2026-09-15 13:09 (prod)** — 3회 · 2,738행 · 3,623 ms, prod Kafka 적재 확인. 실습실 망에서는 호출 불가(호스트 단위 차단)라 로컬은 실측 샘플(2026-09-08)로 단위 테스트 |
| `weather.nowcast` | 기상청 API허브 `VilageFcstInfoService_2.0/getUltraSrtNcst`·`getUltraSrtFcst` (nx=60 ny=127) | 실황 1회 + 예보 1회 | 1시간 · 하루 종일 | `nx:ny:category` (예 `60:127:T1H`) | 발표 시각 `baseDate+baseTime` | **실측 2026-09-14 12:28·12:32** — 2회 호출(실황+예보) · 35건 · 752 ms·982 ms, 로컬 Kafka 적재 확인. 항목은 AI 폴러와 같은 T1H·RN1·REH·WSD·PTY |

- 지하철 `statnId` 는 우리 `station.station_id`(서울 역번호)와 **체계가 다르다.** 대응은 Redis 반영 컨슈머(171)에서 한다.
- 지하철 페이지 경계의 행이 양쪽 페이지에 겹쳐 온다(실측 3,002건 중 고유 `event_id` 3,001). 같은 행은 `event_id` 가 같아 컨슈머가 걸러낸다.
- 날씨 실황 항목은 `obsrValue`, 예보 항목은 `fcstDate·fcstTime·fcstValue` 를 가져 payload 만 보고 구분된다. 발표 시각 판단(실황 매시 정각 + 40분, 예보 매시 30분 + 15분 뒤부터)은 `AI/DATA_ENGINE/collect/weather_nowcast.py` 와 같다.

## 3. 이벤트 (실제 1건, 2026-09-14 11:50 회차)

```json
{
  "event_id": "784932211c0479567199d73ba722caba3b534de1c345579e08433b94c7548dc1",
  "source": "subway.arrival",
  "entity_id": "1009000937",
  "source_generated_at": "2026-09-14T11:46:06+09:00",
  "ingested_at": "2026-09-14T11:50:21.461+09:00",
  "poll_run_at": "2026-09-14T11:50:21+09:00",
  "payload": { "subwayId": "1009", "statnId": "1009000937", "statnNm": "둔촌오륜", "updnLine": "하행",
               "trainLineNm": "개화행 - 올림픽공원방면", "barvlDt": "20", "recptnDt": "2026-09-14 11:46:06",
               "arvlMsg2": "둔촌오륜 출발", "arvlCd": "2", "subwayNm": null, "...": "API 응답 행 원본 그대로 (31개 필드)" }
}
```

Kafka 레코드 키는 `entity_id`, 값은 위 JSON(UTF-8 문자열)이다. 필드 정의·`event_id` 규칙·컨슈머 그룹은 [kafka.md 5절](kafka.md#5-이벤트-계약-s15p21a104-169).
파이썬에서는 `json.loads(record.value)` 뒤 `poll_run_at` 으로 묶으면 회차 스냅샷이 된다.

## 4. 설정

기본값은 `src/main/resources/application-collect.yml`. 환경변수 또는 명령행 `--collect.*` 로 덮어쓴다.

| 환경변수 | 기본 | 뜻 |
| --- | --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | 브로커. 클러스터 파드는 `kafka:9092` |
| `SEOUL_SUBWAY_KEY` (없으면 `SEOUL_API_KEY`) | — | 지하철 실시간 전용 키. 비어 있으면 지하철 소스는 기동 시 비활성 |
| `SEOUL_BIKE_KEY` (없으면 `SEOUL_API_KEY`) | — | 따릉이 키 |
| `KMA_API_KEY` | — | 기상청 API허브 authKey (공공데이터포털 serviceKey 와 별개) |
| `COLLECT_SUBWAY_INTERVAL` · `COLLECT_SUBWAY_WINDOW` | `60s` · `07:30-13:00` | 주기 · 운영 시간 창 |
| `COLLECT_BIKE_INTERVAL` · `COLLECT_BIKE_WINDOW` | `120s` · `07:00-18:00` | |
| `COLLECT_WEATHER_INTERVAL` · `COLLECT_WEATHER_WINDOW` | `1h` · `00:00-24:00` | |
| `COLLECT_DAILY_CALLS` | `1000` | 소스별 하루 호출 상한 (안전장치) |

명령행 전용: `--collect.dry-run=true`(전송 안 함) · `--collect.run-once=true`(한 회차) · `--collect.<소스>.enabled=false` ·
`--collect.http.read-timeout=10s` · `--collect.topics.retention-hours=48`.

창은 KST `HH:mm-HH:mm`, 시작 포함·종료 미포함. `22:00-06:00` 처럼 자정을 넘겨도 되고 `00:00-24:00` 은 하루 종일이다.

## 5. 예산과 운영 시간 창 (S15P21A104-170)

열린데이터광장 키는 **하루 1,000회**(실시간 지하철 키는 이용안내 원문, 일반키는 가정 — api-survey.md 4절)이고, 활용사례 갤러리 등록은
승인 지연 위험으로 이번 주 범위에서 뺐다(2026-09-14). 그래서 목표 주기를 하루 종일 돌리지 않고 **예산을 시간 창에 몰아 쓴다.**

| 소스 | 회차당 호출 | 주기 | 창 | 회차/일 | 호출/일 |
| --- | --- | --- | --- | --- | --- |
| 지하철 | 3 (첨두 4) | 60초 | 07:30-13:00 (5.5h) | 330 | **990** (4회가 붙는 회차만큼 초과 → 예산 가드가 멈춤) |
| 따릉이 | 3 | 120초 | 07:00-18:00 (11h) | 330 | **990** |
| 날씨 | 2 | 1시간 | 하루 종일 | 24 | 48 (별도 키·별도 한도) |

규칙:

- **주기는 fixed delay** — 이전 회차가 끝난 뒤부터 잰다. 회차가 길어져도 호출이 몰리지 않아 하루 호출이 계획을 넘지 않는다(약간 적게 돈다).
- **하루 예산(`CallBudget`)** — 소스별로 호출을 세고(재시도 포함, KST 자정 초기화) 남은 예산이 회차당 호출 수보다 적으면 그날은 멈춘다. 한도 초과 시 서버 응답 코드가 확인되지 않아 우리가 먼저 멈추는 것이다. 프로세스를 재시작하면 0 부터 다시 센다 — 창이 보수적이라 그 안에서는 문제가 없다.
- **지하철 첨두시간** — `total` 이 3,000 을 넘으면 4회째 호출이 붙는다. 4회가 계속되면 330회차 × 4 = 1,320 > 1,000 이라 예산 가드가 약 250회차(4시간 10분)에서 멈춘다. 첨두가 창의 대부분이면 `COLLECT_SUBWAY_INTERVAL=90s`(220회차 × 4 = 880)로 늘리거나 창을 줄인다. 기동 로그의 `하루 계획` 은 최근 회차의 호출 수로 다시 계산된다.
- **창 밖** — 서비스는 Redis TTL 만료로 "재고 모름 → 정적값 강등"으로 내려간다(NFR-A01). 별도 기능이 아니다.
- 발표 시간대가 정해지면 `COLLECT_*_WINDOW` 만 바꾼다. 코드 변경 없음.

## 6. 보호 장치

| 장치 | 규칙 | 근거 |
| --- | --- | --- |
| 재시도 | 타임아웃·IO·5xx 만 최대 2회, 500ms → 1s 백오프. 4xx·API 오류 코드·파싱 실패는 즉시 실패 | NFR-EXT-002 |
| 서킷 브레이커 | 회차가 **연속 3회** 실패하면 **60초** 건너뜀. 정상 코드 외 응답은 전부 실패 | api-survey 4절 결정 5, NFR-EXT-001 |
| 예산 | 위 5절 | 170 |
| 부분 결과 거부 | 오류 응답이 섞이면 그 회차 전체를 버린다 — 오류에 섞인 데이터를 성공으로 오해하지 않기 위해 | probe.mjs 와 같은 규칙 |
| 전송 실패 | 브로커 문제는 브레이커에 세지 않고 로그만 남긴 뒤 다음 회차에 계속 | 외부 API 잘못이 아니다 |
| 키 가림 | 로그·예외 메시지의 URL 에서 인증키를 `{KEY}` 로 바꾼다 (URL 인코딩된 형태 포함) | 시크릿 유출 방지 |
| 폴링은 프로세스를 죽이지 않는다 | 회차 안의 모든 예외는 잡아서 로그로 남긴다 | AI 폴러와 같은 하드 룰 |

## 7. 검증

```bash
cd BE
# 단위 테스트 (호출 0회 — 실측 샘플 docs/external/samples 와 픽스처 src/test/resources/collect 사용)
./gradlew test --tests 'com.ssafy.s15p21a104.collect.*'
# 브로커가 있으면 CollectorKafkaIT 까지 (토픽 설정 확인 + 이벤트 왕복)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 ./gradlew test --tests 'com.ssafy.s15p21a104.collect.*'
```

| 테스트 | 보장하는 것 |
| --- | --- |
| `OperatingWindowTest` · `CallBudgetTest` | 창 경계(종료 미포함·자정 넘김·하루 종일), 예산 카운트·KST 자정 초기화 |
| `EventIdFactoryTest` · `CollectEventJsonTest` | `event_id` 결정성(필드 순서 무관), 계약 필드 7개·순서·시각 형식·null 유지 |
| `RetryingHttpFetcherTest` | 타임아웃·5xx 만 재시도, 4xx 즉시 실패, 시도마다 예산 셈, 키 가림 |
| `SubwayArrivalSourceTest` · `BikeStockSourceTest` · `WeatherNowcastSourceTest` | URL 조립, 페이지 이어받기·종료 조건, 오류 코드→예외, `INFO-200`/`03`→빈 회차, 필드 매핑, 발표 시각 판단 |
| `SourcePollerTest` | 창 밖 미호출, 브레이커 3회→60초, 성공 시 초기화, 예산 부족 미호출, 전송 실패는 브레이커 무관 |
| `CollectTopicsTest` | 토픽 3개 정의값 (168) |
| `CollectProfileContextTest` · `KafkaBeansAbsentTest` | collect 프로파일 배선이 뜬다 / API 서버 컨텍스트에는 Kafka·수집기 빈이 없다 |
| `CollectorKafkaIT` (브로커 필요) | 토픽 3개가 `retention.ms`·`retention.bytes`·`segment.ms` 그대로 존재, 이벤트가 계약 JSON·키로 들어간다 |

실측(2026-09-14, 로컬 compose): `run-once` 로 지하철 한 회차 — 호출 3회 · 3,002행 · 전송 3,002건 · 963ms, JVM 정상 종료.
`subway.arrival` 오프셋 1 → 3,003. 디스크 730KB(lz4, 약 240B/이벤트).
날씨도 같은 방식으로 두 회차 — 호출 2회(실황+예보) · 35건 · 752ms(12:28) · 982ms(12:32).
전부 **1회성 측정치**다. 반복·분포를 갖춘 정식 기록이 아니므로 `docs/perf/README.md` 의 기준선 절에 그렇게 표시해 두었다.

## 8. 배포 (S15P21A104-173)

BE 이미지를 그대로 쓰고 프로파일만 바꾼다. `BE/k8s/**` 는 `Infra/k8s/CONTRACT.md` 1절상 플랫폼(리드) 소유이나,
이 건은 **리드 승인 하에 C 파트가 직접 작성·적용**했다.

| 항목 | 값 |
| --- | --- |
| 매니페스트 | `BE/k8s/prod/be-collector.yaml` · `be-config.env` · `be-secret.env.example` · `kustomization.yaml` |
| 이미지 | `sumgil-be:latest` (같은 이미지 — 수집기 코드가 같은 jar 안에 있다) |
| 환경 | `SPRING_PROFILES_ACTIVE=prod,collect` · `KAFKA_BOOTSTRAP_SERVERS=kafka:9092` · `be-config`(DB·Redis 포인터) · `data-secret`(DB_PASSWORD) · **`be-secret`**(`SEOUL_SUBWAY_KEY`·`SEOUL_API_KEY`·`SEOUL_BIKE_KEY`·`KMA_API_KEY`) · `COLLECT_*_WINDOW` |
| replicas | **1** · `strategy: Recreate` — 파티션 1이고, 파드가 겹쳐 돌면 호출 예산을 두 배로 쓴다 |
| 헬스 | 웹 서버가 없어 HTTP 프로브 없음. 로그(JSON, prod 프로파일)로 본다 |

`be-secret` 은 `CONTRACT.md` 4절이 "필요 시 · 현재 없음" 으로 예약해 둔 자리를 처음 쓴 것이다. 적용 전 prod 에는
Secret 이 `data-secret` 하나뿐이었다.

### 절차

```bash
# 1. 로컬 — 매니페스트 커밋 후 control-plane 으로 동기화 (워커는 레지스트리에서 이미지를 받아 소스가 필요 없다)
NODES=a104 bash Infra/k8s/scripts/deploy/sync-to-nodes.sh

# 2. 로컬 — 시크릿은 sync 대상에서 제외되므로 따로 올린다 (sync-to-nodes.sh 가 tar 에서 뺀다)
scp <로컬 be-secret.env> a104:~/sumgil/BE/k8s/prod/be-secret.env

# 3. 노드 — 렌더링 확인 (20분 빌드 전에 파일 문제를 먼저 잡는다). 리소스 7개 + be-secret-<해시>
ssh a104 'cd ~/sumgil && sudo kubectl kustomize BE/k8s/prod | grep -c "^kind:"'

# 4. 노드 — 이미지 빌드·push. Gradle 멀티스테이지라 오래 걸린다. 백그라운드로 띄운다
ssh a104 'cd ~/sumgil && nohup bash Infra/k8s/scripts/deploy/build-push.sh be > /tmp/build-be.log 2>&1 & echo started'
ssh a104 'tail -5 /tmp/build-be.log'   # "✓ sumgil-be pushed" 면 완료

# 5. 노드 — 적용. apply.sh 가 kubectl apply -k 로 폴더 전체를 적용하므로 be-collector 도 함께 만들어진다
ssh a104 'cd ~/sumgil && bash Infra/k8s/scripts/deploy/apply.sh'
ssh a104 'sudo kubectl rollout status deployment/be-collector -n prod --timeout=180s'
```

`apply.sh` 는 `be`·`fe` 만 rollout 을 기다린다. `be-collector` 는 목록에 없어 5번 마지막 줄을 수동으로 친다.

### 검증

```bash
# 기동 로그 — 소스별 예산 계획이 찍힌다
ssh a104 'sudo kubectl logs deploy/be-collector -n prod --tail=40'

# 토픽 오프셋 — 0 이 아니면 들어간 것
ssh a104 'sudo kubectl exec -n prod sts/kafka -- /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server localhost:9092 --topic bike.stock'

# 이벤트 1건 눈으로
ssh a104 'sudo kubectl exec -n prod sts/kafka -- /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic bike.stock --from-beginning --max-messages 1'
```

로그의 `⚠ 계획이 예산을 넘는다` 는 창·주기 오설정, `인증키가 없어 비활성화한다` 는 `be-secret` 키 이름 불일치다.

롤백은 `sudo kubectl delete deployment be-collector -n prod`. 토픽·`be`·데이터 계층에 영향이 없다.

### 적용 결과 (2026-09-15)

기동 28.8초(JPA·탐색 그래프 로드 포함) 뒤 세 소스가 첫 회차를 돌았다. 파드 `be-collector-7cc4f995b6-4tdzg`,
워커 노드(`ip-172-26-10-6`) 배치.

| 소스 | 첫 회차 (13:09:17) | 호출 | 행 | 전송 | 소요 |
| --- | --- | --- | --- | --- | --- |
| `weather.nowcast` | 실황+예보 | 2회 | 35 | 35 | 2,903 ms |
| `bike.stock` | 3분할 | 3회 | **2,738** | 2,738 | 3,623 ms |
| `subway.arrival` | 3분할 | 3회 | 2,956 | 2,956 | 3,914 ms |

토픽 끝 오프셋(13:12 기준): `subway.arrival` 5,883 · `bike.stock` 2,738 · `weather.nowcast` 35.
**토픽만 있고 비어 있던 상태가 해소됐다** — AI `ai-spark` 컨슈머가 받을 이벤트가 생겼다.
Kafka ClusterIP 는 `10.43.134.226` 으로 이전과 같아 AI 쪽 `/etc/hosts` 갱신이 필요 없다.

- **따릉이가 EC2 에서 처음 성공했다.** 실습실 망에서 `openapi.seoul.go.kr` 이 호스트 단위로 막혀 있어
  169 까지 실호출을 못 했던 항목이다. 배포 전 노드에서 무인증 요청으로 경로를 먼저 확인했고
  (`HTTP 500 · 152 ms` — 키·경로 없는 루트 요청이라 500 이 정상), 실제 수집에서 2,738행을 받았다.
- **대여소가 2,738곳으로 정본(2,731)보다 7곳 많다.** 정본은 2026-09-09 `bikeList` 스냅샷이라 그 사이
  신설된 것으로 보인다. `bike_station` 재적재 시점 판단과 `bike_stock_pred` 로더(172)에서 확인할 항목이다.
- 지하철 2,956행은 같은 날 로컬 실측(11:12, 2,872행)과 다르다 — 시각에 따라 잡히는 열차 수가 달라
  회차마다 총량이 변한다(`total` 기준 3회 또는 4회 분할).

### 알아둘 것

- **`sumgil-be:latest` 가 함께 갱신된다 — `be` 재시작이 곧 185·186 배포다.** 수집기 코드가 같은 이미지에
  있어 재빌드가 필수다. `be` Deployment 는 스펙이 안 바뀌어 재시작되지 않으므로 배포 후에도
  **09-14 14:15 무렵 이미지(`sha256:f2c1e1cc…`)로 계속 돈다** — 185(14:51)·186(14:52)·ROUTE 통합(14:57)이
  그 뒤라 지금 `be` 에는 좌표 기반 경로 검색·도보 geometry 코드가 없다. 올리는 시점은 A 파트가 정한다:
  `sudo kubectl rollout restart deployment/be -n prod` (`apply.sh` 는 `latest` 재push 만으로 rollout 을
  일으키지 않는다).
- **`KAKAO_REST_API_KEY` 가 없는 것은 현재 정상이다.** `KakaoWalkProperties.isConfigured()` 가 키가 비면
  카카오 호출 자체를 건너뛰고 빈 값을 돌려준다(186 주석: "원천 선정·쿼터·요금은 팀 합의 사항이라 실제 키는
  아직 없다"). 키 없이 재시작해도 장애가 아니라 도보 구간 geometry 가 안 나오는 정도다. 키가 생기면
  `be-secret` 에 넣고 `be.yaml` 의 `envFrom` 에 `secretRef: be-secret` 을 붙인다 — Secret 자리는 173 에서
  이미 만들었다.
- **로컬과 prod 가 같은 서울시 키를 쓴다.** 하루 1,000회 예산을 나눠 쓰므로 prod 수집기가 뜨면 로컬 수집기는
  중단한다. AI 파트도 EC2 에서 D−1 승하차를 수집하므로(S15P21A104-201) 같은 키인지 확인이 필요하다.
- **지하철 운영 창이 `10:00-15:30` 이다.** 발표가 그 밖이면 `be-config.env` 의 `COLLECT_SUBWAY_WINDOW` 를
  옮기고 다시 apply 한다. 폭(5시간 30분)은 유지해야 예산 안에 든다.

### 저녁 수집기 — 둘째 키로 15:30 이후 창 (2026-09-18, 170 후속)

팀원이 밤에도 작업하게 되어 둘째 인증키(다른 계정 발급)를 받았다. 코드는 소스마다 키 하나·창 하나·예산 카운터 하나라
키를 도중에 바꿀 수 없으므로, **파드를 하나 더 띄우는 것**으로 풀었다 — `be-collector-evening.yaml`.

| | 낮 `be-collector` | 저녁 `be-collector-evening` |
| --- | --- | --- |
| 지하철 창 | `10:00-15:30` (be-config.env) | `15:30-21:00` (Deployment env 가 덮음) |
| 따릉이 창 | `07:00-18:00` | `18:00-24:00` (자정을 넘기지 않는다 — CallBudget 이 KST 자정에 리셋돼 다음 날 예산을 새벽에 태운다) |
| 날씨 | `00:00-24:00` | **없음** — `be-secret` 을 통째로 물리지 않아 `KMA_API_KEY` 가 없고, 키 없는 소스는 기동 시 비활성화된다 |
| 키 | `SEOUL_SUBWAY_KEY`·`SEOUL_BIKE_KEY` | `be-secret` 의 `SEOUL_SUBWAY_KEY_EVENING`·`SEOUL_BIKE_KEY_EVENING` 을 `secretKeyRef` 로 같은 이름에 꽂는다 |
| 예산 | 990 / 1,000 | 지하철 990 · 따릉이 540 |

- 두 창은 15:30 에서 맞닿고(종료 미포함·시작 포함) 겹치지 않는다. 같은 토픽에 쓰지만 중복 이벤트가 없다.
- **컨슈머는 두 창의 합 `10:00-21:00` 을 본다** — `be-consumer.yaml` 의 env 가 `be-config` 값을 덮는다. 저녁 창을 옮기면 같이 바꾼다.
- 둘째 키 두 개는 `be-secret.env.example` 에 추가했다. `render-secrets.sh` 가 example 의 키를 전부 요구하므로
  **GitLab 변수에도 같은 이름으로 등록해야 렌더가 된다** (`register-gitlab-vars.sh` 가 example 에서 이름을 읽는다).
  `be-secret` 내용이 바뀌어 해시 접미사가 바뀌면 낮 `be-collector` 도 한 번 재시작된다 — 15:30 이후에 적용하면 잃는 회차가 없다.
- `apply.sh` 의 rollout 대기 목록에 없다. 적용 뒤 `kubectl rollout status deployment/be-collector-evening -n prod` 를 직접 본다.
- 확인: 저녁 파드 로그에 `subway.arrival 운영 시간 창 15:30-21:00 — 지금 안`, 날씨는 `weather 소스 인증키가 없어 비활성화한다`.
  Redis `subway:arrival:status` 의 `window` 가 `10:00-21:00`, 15:30 이후 `subway:arrival:{id}` TTL 이 계속 갱신되면 끝.

## 9. 밟은 함정

- **`Map.copyOf` 는 null 값을 거부한다.** API 행에는 `subwayNm: null` 같은 필드가 흔해 payload 복사에 쓰면 NPE. `Collections.unmodifiableMap(new LinkedHashMap<>(…))` 로 감싼다.
- **`OffsetDateTime.toString()` 은 초가 0 이면 `:00` 을 생략한다** (`11:48+09:00`). 와이어 형식은 `ISO_OFFSET_DATE_TIME` 으로 항상 초까지 찍는다. 테스트에서 `toString()` 과 비교하면 어긋난다.
- **기상청 예보 발표 시각** — 10:50 에 볼 예보는 09:30 이 아니라 **10:30** 발표분이다(매시 30분 발표, 45분부터 안정). AI 폴러 규칙을 그대로 옮겼는데 기대값을 잘못 적어 테스트가 한 번 틀렸다.
- **`retention.ms` 만 걸면 48시간에 지워지지 않는다.** 삭제는 닫힌 세그먼트 단위인데 기본 세그먼트가 7일·1GiB 라 활성 세그먼트가 안 닫힌다. `segment.ms=6h`·`segment.bytes=128MiB` 를 같이 건다 (kafka.md 4절).
- **첨두시간 `total` > 3,000.** 2026-09-08 11:24 에는 2,953 이었는데 09-14 11:50 에는 3,009. 3회 고정이면 마지막 노선의 열차가 잘린다 → `total` 을 보고 4회째까지 이어 받는다.
- Java 메서드 이름은 숫자로 시작할 수 없다 (`4xx_는_…` 컴파일 오류).
