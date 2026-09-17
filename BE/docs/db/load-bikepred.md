# 따릉이 재고 예측 정적 적재 (S15P21A104-172)

> `bike_stock_pred` 를 AI 배치 산출물에서 채우는 로더. 코드는 `com.ssafy.s15p21a104.load.bikepred`,
> 원천은 **저장소에 없다** — AI EC2 가 매일 만드는 파일을 받아서 읽는다.
> 값을 계산하지 않는다. 예측은 AI 파트(`AI/app/BIKE/pipeline`)가 만들고 우리는 그대로 옮긴다.

## 실행

```bash
# 1) 최신 산출물 받기 (AI EC2 → AI/data/BIKE/serving/)
node BE/scripts/data/bikepred-fetch.mjs            # --list 로 원격 목록만 볼 수도 있다

# 2) 적재
cd BE
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=bikepred --load.dry-run=true'   # 파싱·검증·건수만
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=bikepred'                       # 실제 적재
```

**`bikepred` 는 기본 `sources` 에 없다.** 원천 파일을 먼저 받아야 하므로 기본에 넣으면 파일이 없는 사람의 전체 적재가 실패한다.
대여소 마스터(`bike`) 적재는 선행 조건이 **아니다** — 마스터에 없는 대여소도 적재하고 경고만 남긴다(아래 "값 규칙").

## 원천

배치(`AI/DATA_ENGINE` 의 `bike-avg-batch.timer`)가 매일 **03:00 KST** 에 워커 노드에서 만든다.

| 항목 | 값 |
| --- | --- |
| 노드 | `j15a104a` (AI 데이터 엔진 저장소가 따로 클론돼 있다) |
| 경로 | `~/Soomgil-INFRA-ai-data-monitoring/AI/data/BIKE/serving/` |
| 파일 | `bike_stock_pred_<YYYYMMDD>-<HHMMSS>.csv` + `.parquet` + `.meta.json` |
| 열 8개 | `rental_id, dow_type, time_slot, exp_bikes, p_empty, p_full, source, prediction_source` |

**"최신" 은 파일명 정렬로 고른다.** 이름에 생성시각이 들어 있어 사전순 = 시간순이다.
이 규칙은 세 곳이 같아야 한다 — 내려받기 스크립트, 자바 로더(`CsvBikeStockPredSource`),
그리고 **AI 서빙 API**(`AI/app/BIKE/service.py` 의 `sorted(glob)`). 다르게 고르면 우리가 적재한 표와 AI API 응답이
서로 다른 배치 결과가 된다.

> **AI 서빙 API 는 적재 원천이 아니다.** `GET /bike/stations/{rental_id}/stock` 은 대여소 하나씩 응답하는
> **조회 창구**이고, 그 뒤에서 읽는 파일이 이 로더가 읽는 CSV 의 parquet 짝이다. 40만 행을 적재하려고 그 API 를
> 대여소 수만큼 부르는 것은 같은 파일을 한 번 읽는 것보다 나을 이유가 없다. 티켓 본문의 "CSV → AI API 교체" 는
> 이 지점에서 사실과 다르다. 표 전체를 주는 엔드포인트가 생기면 그때 `BikeStockPredSource` 구현을 하나 더 만든다.

## 2026-09-17 적재 결과 (로컬 postgres:16)

산출물 `bike_stock_pred_20260917-014432.csv` (아티팩트 `avg-refreshed`, 29 MB).

| 항목 | 값 |
| --- | --- |
| 원천 | **406,656행** · 대여소 **2,824** (= 2,824 × 요일 3 × 슬롯 48, 빈 칸 없음) |
| 건너뜀 | **0행** |
| 적재 | **406,656행** · 대여소 2,824 — 원천과 같다(거르지 않는다) |
| 출처 등급 | `observed_avg` 375,342 (92.3%) · `station_time_fallback` 31,266 (7.7%) · `station_global_fallback` 48 (0.0%) |
| 마스터에 없는 대여소 | **96곳** — 경고로 남기고 함께 적재 |
| 적재 시간 | 12.3초 (약 32,986 행/초). 파싱 포함 16.7초 |

**1회 측정치다.** 규약 원칙 3(워밍업 + 5회, median·p95)을 채우지 않았으므로 기준선으로만 쓰고 개선 근거로 인용하지 않는다.

표본 대조 — `ST-10` 평일(`dow_type=0`) 18시 슬롯(`time_slot=36`):

| | 원천 CSV | DB |
| --- | --- | --- |
| `exp_bikes` | 10.923497267759563 | **10.9** |
| `p_empty` | 0.06929955290611028 | **0.069** |
| `p_full` | 0.47690014903129657 | **0.477** |
| `source` · `prediction_source` | avg · observed_avg | avg · observed_avg |

## 2026-09-17 prod 적재 결과

로컬과 같은 산출물(`bike_stock_pred_20260917-014432.csv`)을 SSH 터널로 넣었다. **로컬과 전부 일치한다.**

| 항목 | 값 |
| --- | --- |
| 적재 전 | 0행 |
| 적재 후 | **406,656행** · 대여소 **2,824** |
| 출처 등급 | `observed_avg` 375,342 · `station_time_fallback` 31,266 · `station_global_fallback` 48 |
| 마스터 미등록 | 96곳 경고 후 함께 적재 |
| 표본 `ST-10` 평일 18시 | `10.9 / 0.069 / 0.477 / avg / observed_avg` — CSV 원본과 일치 |
| 적재 시간 | 27.8초 (약 14,626 행/초). 파싱 포함 32.7초 |

터널을 타서 로컬(약 32,986 행/초)보다 느리다. **둘 다 1회 측정치이고 조건이 다르므로 나란히 놓고 배수를 계산하지 않는다** (perf 규약 원칙 5).

### 선행 배포 (이번 한 번만)

V5 를 prod 에 넣기 위해 이미지를 새로 빌드하고 `be`·`be-consumer` 를 재시작했다. **다음 적재부터는 필요 없다** — 열이 이미 있으므로 터널·적재·정리 세 단계면 된다.

```bash
NODES=a104 bash Infra/k8s/scripts/sync-to-nodes.sh
ssh -i "$PEM" "$NODE" 'cd ~/sumgil && nohup bash Infra/k8s/scripts/build-push.sh be > /tmp/build-be.log 2>&1 & echo started'
ssh -i "$PEM" "$NODE" 'sudo kubectl rollout restart deployment/be-consumer -n prod'   # 마이그레이션은 먼저 뜨는 쪽이 돌린다
ssh -i "$PEM" "$NODE" 'sudo kubectl rollout restart deployment/be -n prod'            # 이미지 정합성 — 아래 주의 참고
```

주의할 점 넷.

- **`be`·`be-consumer`·`be-collector` 가 같은 `sumgil-be:latest` 를 쓴다.** 빌드는 한 번이고 재시작만 나눈다.
- **`be` 도 반드시 새 이미지로 올린다.** DB 이력에 V5 가 있는데 파드 이미지에 `V5__*.sql` 이 없으면 다음 재시작 때 Flyway 검증이 실패해 앱이 뜨지 않는다. 한쪽만 올리고 두면 시한폭탄이 된다.
- **`be-collector` 는 재시작하지 않았다.** 수집 시간 창이 열려 있어 회차가 끊긴다. 코드도 안 바뀌었고, 새 이미지에 V5 가 있으므로 나중에 재시작돼도 안전하다.
- **`be-consumer` 재시작은 그때까지 쌓인 컨슈머 로그를 지운다.** perf 기록용 로그가 필요하면 재시작 전에 먼저 받는다 (`kubectl logs --since=24h`).

빌드가 캐시로 몇 초 만에 끝날 수 있다. 그때는 jar 안을 직접 확인한다.

```bash
ssh -i "$PEM" "$NODE" 'C=$(sudo docker create <레지스트리>/sumgil-be:latest); sudo docker cp $C:/app/app.jar /tmp/v.jar; sudo docker rm $C; unzip -l /tmp/v.jar | grep db/migration/V; sudo rm /tmp/v.jar'
```

## 값 규칙

- **원천의 배정밀도를 DB 스케일로 줄인다.** `exp_bikes` 는 `NUMERIC(5,1)`, 확률 둘은 `NUMERIC(4,3)` 이라
  원천 값을 그대로 넣을 수 없다. 반올림은 HALF_UP.
- **`source` 는 CSV 열을 읽는다** (하드코딩하지 않는다). `avg` | `model` 이며, lightgbm 예측기를 써도 행 값은 `model` 이라
  예측기 이름과 다르다.
- **`prediction_source` 는 별도 열이다** (V5). `source` 와 축이 다르다 — `source` 는 *어떤 예측기인가*,
  `prediction_source` 는 *그 값이 관측인가 대체인가*다. 예측기를 바꿔도 대체값은 계속 생기므로 한 열에 섞으면 값 조합이 복잡해진다.
  - `observed_avg` 그 대여소·요일·슬롯의 실제 관측 평균
  - `station_time_fallback` 같은 대여소·같은 슬롯의 **다른 요일** 평균으로 메움
  - `station_global_fallback` 같은 대여소 **전체** 평균으로 메움
  - **다른 대여소 값은 끌어오지 않는다.** 대체 범위가 대여소 안으로 닫혀 있다.
  - 열이 없던 시절 산출물은 `NULL` 이다. "라벨 없음" 과 "관측" 은 다르다.
- **대체값을 버리지 않고 라벨과 함께 싣는다.** "표본 부족 구간에 값을 채우지 않는다" 원칙이 막으려는 것은
  *채워 놓고 진짜인 척하는 것*이지 *채웠다고 표시하고 두는 것*이 아니다. 읽는 쪽이 등급을 보고 판단한다.
  관측값만 원하면 `WHERE prediction_source = 'observed_avg'` 한 줄이다.
- **마스터에 없는 대여소도 적재한다.** 예측 표가 대여소 마스터(09-09 스냅샷 2,731곳)보다 최근이라 신설 대여소가
  정상적으로 섞인다. 혼잡도처럼 오류로 막으면 그 대여소의 예측이 통째로 사라지므로 경고만 남긴다.
  대여소 마스터 갱신은 별건이다(72 후속).
- 숫자 칸이 비었거나 숫자가 아니면 **행을 만들지 않는다.** AI 가 격자를 이미 다 채워 보내므로 빈 칸은
  파이프라인이 바뀌었다는 신호이고, 우리가 메우면 그 신호가 사라진다.

## 데이터 흐름

```
AI EC2 serving/ ─(bikepred-fetch.mjs)─▶ AI/data/BIKE/serving/*.csv ─▶ CsvBikeStockPredSource(최신 파일 선택 + meta 행 수 대조)
                                                                              │
                                                                              ▼
                                                    BikeStockPredParser(스케일·라벨, 40만 행 스트리밍)
                                                                              │
                                                                              ▼
              MasterValidator.validateBikeStockPred(중복키·범위·확률, 마스터 대조는 경고) ─▶ UpsertWriter.upsertBikeStockPred
```

## 읽는 쪽에 미치는 영향

- `bike_stock_pred` 가 처음 채워졌다. `RouteGraphRegistry.bikeStock()` 이 지금은 빈 맵을 돌려주는 스텁인데,
  이 표 조회로 교체하는 것은 **A 파트 변경**이다 — 적재가 끝났음을 통보한다.
- **`prediction_source` 를 읽는 쪽이 보고 판단할 수 있다.** 7.7%가 대체값이고 대여소 864곳에 걸쳐 있다.
  재고 게이트를 보수적으로 걸 근거로 쓸 수 있다.
- 대여소 **2,824곳**이 들어 있어 마스터(2,731곳)보다 많다. 마스터 기준으로 조인하면 96곳이 빠진다.
- 날짜 축이 없다. 재학습 때만 표가 새로 만들어지므로 조회는 (대여소, 요일, 슬롯) 세 값이면 된다.

## 스키마 변경

`V5__bike_stock_pred_prediction_source.sql` — `prediction_source VARCHAR(32) NULL` 추가.
폭 32 는 가장 긴 값 `station_global_fallback`(23자)에 여유를 둔 것이다. `source` 가 폭 부족으로 V2 에서 이미
한 번 넓어진 전례를 반영했다.

## 테스트

```bash
cd BE
./gradlew test --tests 'com.ssafy.s15p21a104.load.bikepred.*'   # 파서 11 + 검증 11 + 원천 10 + 설정 6
./gradlew test --tests '*UpsertWriterIT'                         # bike_stock_pred 멱등·덮어쓰기·라벨 보존 (postgres 필요)
node --test "BE/scripts/data/test/bikepred-fetch.test.mjs"       # 최신 선택 규칙 7
```

- `BikeStockPredParserTest`(11): 8열 읽기, DB 스케일 축소, 빈 라벨 → null, fallback 보존, 빈 숫자·비숫자 건너뜀,
  집계 경고, 통계, 필수 열 누락 시 중단, `prediction_source` 열 없어도 읽기
- `BikeStockPredValidatorTest`(11): 중복 키, 요일·슬롯 범위, 확률 0~1, 음수 대수, `source`·`prediction_source` 폭,
  **마스터 미등록은 경고**, 빈 마스터면 대조 건너뜀
- `CsvBikeStockPredSourceTest`(10): 파일·폴더 경로, 최신 선택, parquet·meta 무시, meta 행 수 대조(일치·불일치·없음·깨짐),
  경로 포함 오류, BOM·CRLF
- `BikePredPropertiesTest`(6): 기본값, 대소문자, 기본 경로, 모르는 값·`api` 거절
- 증적: `.claude/tdd/172-bikepred-load.tdd.md`

## 남은 일 (후속)

- **주기 갱신.** 배치가 매일 03:00 에 새 파일을 만들지만 받아서 적재하는 것은 아직 수동이다.
  얼마나 자주 다시 적재할지는 정하지 않았다. 예측 표가 요일·시간대 평균이라 하루 이틀로 크게 변하지 않으므로
  발표 전에 한 번 갱신하는 정도면 충분해 보인다 — 필요하면 `bikepred-fetch.mjs` + 적재 두 줄이다.
- **대여소 마스터 갱신** (72 후속). 지금 96곳이 예측만 있고 마스터에 없다.
- **AI 벌크 엔드포인트.** 표 전체를 주는 API 가 생기면 원천 구현을 하나 더 만든다. 지금은 대여소 단위뿐이다.
