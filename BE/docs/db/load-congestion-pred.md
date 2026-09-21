# 혼잡도 예측 정적 적재 (S15P21A104-305 · 304)

AI CROWD 배치가 만든 링크 단위 혼잡도 예측을 `congestion_pred` 에 넣는다. **AI 는 PG 에 직접 쓰지 않고
BE load job 이 넣는다** — 회신 04 L-2 에서 확정한 구조이고 172(`bike_stock_pred`)와 같다.

## 실행

```bash
# 1) 오늘 이후 산출물 받기 (AI 워커 j15a104a → AI/data/CROWD/serving/) — CSV + 사이드카, 이미 있으면 건너뜀
node BE/scripts/data/crowdpred-fetch.mjs
node BE/scripts/data/crowdpred-fetch.mjs --list              # 원격 목록만 본다 (받을 것에 ← 표시)
node BE/scripts/data/crowdpred-fetch.mjs --since 2026-09-20  # 기준일 지정 · --all 이면 날짜 제한 없이 전부

# 2) 적재
cd BE && SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun \
  --args='--load.sources=crowdpred --load.dry-run=true'   # 파싱·검증·건수만
cd BE && SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun \
  --args='--load.sources=crowdpred'                       # 실제 적재
```

`crowdpred` 는 기본 `sources` 목록에 **없다.** 원천 파일을 먼저 받아야 하므로 기본에 넣으면 파일이 없는
팀원의 전체 적재가 실패한다(`bikepred` 와 같은 이유).

로더는 `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`·`REDIS_HOST`·`REDIS_PORT` 를 요구한다(`load-prod.md` 2-2).
로컬은 `.env` 에 DB 변수가 없으니 docker compose 의 값을 셸에 직접 준다. 없으면
`Driver claims to not accept jdbcUrl, ${DB_URL}` 로 컨텍스트가 뜨지 않는다.

> 수집 스크립트는 **"최신 하나" 를 고르지 않는다.** 대상 날짜가 기준일(기본 오늘, Asia/Seoul) 이후인
> 산출물을 전부 받아 폴더를 동기화하고, 같은 날짜의 최신 회차는 **로더가** 고른다(아래 "값 규칙").
> 로컬 `serving/` 에 과거 날짜 파일이 남아 있어도 조회가 `pred_date = 오늘` 이라 읽히지 않지만, 적재 로그의
> 날짜 목록에 섞이니 치우는 편이 깔끔하다.

## 원천

| | |
| --- | --- |
| 만드는 곳 | AI CROWD 배치 `crowd-batch-predict.timer` — **워커 노드 `j15a104a`**. 매일 09:30 KST(+랜덤 지연 ≤5분), 오늘·내일 2일치. 컨트롤플레인 `a104` 에는 없다 |
| 서버 경로 | `ubuntu@j15a104a.p.ssafy.io:~/Soomgil-INFRA-ai-data-monitoring/AI/data/CROWD/serving/` |
| 파일 | `predictions_<YYYY-MM-DD>_<HHMMSS>.csv` + **사이드카** `.meta.json`. `<YYYY-MM-DD>` 는 **대상 날짜**, `<HHMMSS>` 는 **UTC 생성 시각** — 생성 날짜는 이름에 없다 |
| 같은 폴더의 다른 것 | `predictions_<날짜>.meta.json`(상세 meta) · `predictions_<날짜>.parquet` · `predictions_link_<날짜>.parquet` — 이름 규칙으로 걸러진다 |
| 계약 | `AI/app/CROWD/SERVING_CONTRACT.md` 8·8.1·8.2절 · 통지 07·08 |
| 하루치 | 21,684행 · 링크 556 · 역 286 · 2.9 MB (2026-09-21 실측, 09-20 샘플과 같다) |

열 10개는 순서까지 회신 04 6.1절에서 확정했다.

```
pred_date, line, from_station_no, to_station_no, direction, time_slot, level, data_status, pred_source, predictor_version
```

사이드카는 키가 셋뿐이다. **필수다** — `generated_at` 이 `congestion_pred` 의 NOT NULL 열이고 행 수
대조에 쓴다. 서버가 UTC 라 `+00:00` 으로 오는데, 열이 `TIMESTAMPTZ` 고 파서가 `OffsetDateTime` 이라 시간대
가정 없이 같은 시점으로 들어간다(통지 08 의 확인 요청에 답한 근거).

```json
{"target_date": "2026-09-21", "row_count": 21684, "generated_at": "2026-09-21T06:31:13+00:00"}
```

## 값 규칙

- **`level` 은 NULL 을 허용하고 상한이 없다.** 빈 칸은 그대로 NULL 이다 — 0 으로 채우면 "혼잡도 0%" 와
  "모른다" 가 섞인다. 이유는 `data_status` 가 따로 말한다. 100 을 넘는 값도 그대로 넣는다(실측 최대 164.4).
- **`direction` 은 원천 값을 그대로 넣는다.** 2호선이라도 지선 구간은 내선/외선이 아니라 상선/하선으로
  온다. 역번호 순서로 재추론하지 않는다 — `from→to` 가 이미 방향 있는 링크다.
- **`time_slot` 이 48개가 다 오지 않는다.** 운행 없는 새벽(2~10)은 행 자체가 없어 실측 39종이다.
  "48 × 링크 수" 로 가정하면 어긋난다.
- **한 번 돌 때 날짜가 다른 파일이 둘 생기고, 같은 대상 날짜가 이틀에 걸쳐 두 번 만들어진다.** 배치 기본이
  `--today --tomorrow` 라 오늘·내일을 따로 쓰고, 오늘의 "내일치" 는 다음 날 "오늘치" 로 다시 만들어진다.
  둘 다 00:30 UTC + 랜덤 지연이다. 그래서
  - 수집 스크립트는 기준일 이후 산출물을 **전부** 받는다. 고르지 않는다.
  - 로더는 **대상 날짜마다 사이드카 `generated_at` 이 가장 늦은 회차 하나**를 읽는다(같으면 파일명이 뒤인 것).
    파일명 `_HHMMSS` 로 고르면 안 된다 — UTC 시각만 있고 생성 날짜가 없어, 전날 `_003400` 생성분과 당일
    `_003100` 생성분 중 **옛것이 뒤로 정렬된다**(304, 트러블슈팅 D16). 당일 생성분은 전날 실적이 lag 로
    들어간 것이라 그쪽이 이겨야 한다.
- **`generated_at` 은 산출 시각, `updated_at` 은 적재 시각이다.** 재적재 판정 근거라 구분한다. 한 번에 읽은
  파일이 여럿이면 `generated_at` 은 그중 가장 늦은 값 하나가 전 행에 들어간다(305 설계). 같은 배치 회차면
  1초 차이지만, 날짜별 파일이 다른 회차에서 왔다면 앞 날짜 행의 값이 실제보다 늦게 기록된다 — 후속.
- 적재는 upsert 라 **멱등**이다. 같은 파일을 다시 넣어도 행 수가 늘지 않고 값만 갱신된다.

### 역번호 매핑

혼잡도 통계 적재와 **같은 표**(`CrowdStationCodes`)를 재사용한다. 원천이 같은 서울교통공사 외부역코드
체계이기 때문이다(통지 07 4절). 환승역은 우리 `station_id` 가 노선별 역사코드 중 최솟값이라 합쳐진다 —
4호선 서울역 `426` → `150`, 9호선 종합운동장 `4130` → `218`. 기본키에 `line_id` 가 있어 충돌하지 않는다.

**가상 역번호(9001 성수E 등)는 이 파일에 없다.** 별칭표에 항목이 있어도 쓰이지 않는다.

## 172(재고 예측)와 다르게 한 것

| 항목 | 172 | 305 | 왜 |
| --- | --- | --- | --- |
| 사이드카 meta | 없어도 경고만 | **없으면 중단** | `generated_at` 이 NOT NULL 열이라 넣을 값이 없다 |
| `row_count` 불일치 | 경고 | **중단** | 잘린 파일을 넣으면 그날 예측이 반쪽이 된다 |
| 마스터에 없는 대상 | 경고 후 적재 | **오류** | 예측 표가 새 역을 만들 원천이 아니다 — 없으면 매핑이 깨진 것 |
| 수집 스크립트 | 최신 하나 | **기준일 이후 전부** | 배치가 2일치를 만들고 같은 날짜가 두 회차라 이름으로 못 고른다(304) |

## 2026-09-21 prod 적재 결과 (304)

AI 배치가 워커에 배포된 날(통지 08). 수동 실행분(15:31 KST)을 받아 넣었다.

```
받음     predictions_2026-09-21_063113.csv · predictions_2026-09-22_063114.csv (+ 사이드카 2) — 원격 10개 중 CSV 2개
dry-run  원천 43368 행 · 날짜 [2026-09-21, 2026-09-22] · 링크 556 · 슬롯 39종 · 건너뜀 0
         출처 {model=41496, lookup_line9=1872} · 검증 오류 0
적재     congestion_pred · 43368 행 · 3723 ms · 11649 행/초   (SSH 터널 경유 · 1회 측정치)
```

| `pred_date` | 행 | `level` 있음 | 링크 | 슬롯 | 출처 |
| --- | --- | --- | --- | --- | --- |
| 2026-09-21 | 21,684 | 21,450 | 556 | 39 | model · lookup_line9 |
| 2026-09-22 | 21,684 | 21,450 | 556 | 39 | model · lookup_line9 |

노선별 행은 아래 09-20 표와 같다(1호선 702 … 9호선 936). 이번 회차엔 `lookup_negative` 가 없다(09-20 샘플은 172행).

API 확인 — 서울역(150)→강남(222), 16:55 KST:

| | `congestionPercent` | `congestionGrade` | `predictionBasis` |
| --- | --- | --- | --- |
| 적재 전 | 35.5 | LOW | `WEEKDAY_AVERAGE` (노선 평균 폴백, `congestion` 표) |
| 적재 후 | 75.7 | MEDIUM | `RECENT_7D` (링크 예측, `congestion_pred`) |

**성능 수치는 1회 측정치라 `docs/perf/README.md` 규약(워밍업 + 5회, median·p95)을 충족하지 않는다.**
로컬 직결은 2,014 ms · 21,533 행/초 — 터널 오버헤드가 섞여 있어 나란히 비교하지 않는다.

## 2026-09-20 샘플 적재 결과 (로컬 postgres:16, 305)

```
혼잡도 예측: 원천 21684 행 · 날짜 [2026-09-20] · 링크 556 · 슬롯 39종 · 건너뜀 0
             · 적재 대상 21684 행 · 출처 {model=20576, lookup_negative=172, lookup_line9=936}
적재 congestion_pred · 21684 행 · 580 ms · 37386 행/초
```

검증 오류 0 · 경고 0 · 모르는 역번호 0.

| 노선 | 행 | 링크 |
| --- | --- | --- |
| 1호선 | 702 | 18 |
| 2호선 | 3,900 | 100 |
| 3호선 | 2,496 | 64 |
| 4호선 | 1,950 | 50 |
| 5호선 | 4,290 | 110 |
| 6호선 | 2,808 | 72 |
| 7호선 | 3,198 | 82 |
| 8호선 | 1,404 | 36 |
| 9호선 | 936 | 24 |

DB 집계가 CSV 실측과 일치한다 — 21,684행 · 값 21,402 · 결측 282 · 최소 0.0 · 최대 164.4 · 슬롯 39종.
결측 282는 `data_status=no_calibration` 282행과 정확히 겹친다.

표본 손대조(DB = CSV):

| 링크 | 슬롯 | DB | CSV 원본 |
| --- | --- | --- | --- |
| 150→151 (1호선 하선) | 0 | 1.7 | 1.7229770879488375 |
| 2549→2555 (5호선 마천지선 하선) | 17 | 19.9 | 19.894586335650523 |
| 4126→4127 (9호선 상선, `lookup_line9`) | 17 | 10.9 | 10.898517080303831 |

멱등성: 같은 파일을 다시 적재해도 21,684행 그대로(660 ms). 2일치 픽스처(오늘·내일 + 같은 날짜 재생성분)로
날짜별 하나씩 골라 43,368행이 들어가는 것도 확인했다.

## 9호선

AI 가 9호선 2·3단계 13역(언주 4126 ~ 중앙보훈병원 4138)을 편입해 하루 936행이 새로 들어온다.
`pred_source=lookup_line9` 이고 `predictor_version` 도 `lookup:line9_2025_2026` 으로 다르다 —
모델을 타지 않고 기준선만 쓴다. 9호선은 전날 승하차 원천이 없어(열린데이터광장 `getStnPsgr` 가
1~8호선만 준다) 모델 입력 13개 중 6개가 죽기 때문이다(통지 07 3절).

**9호선은 역번호 오름차순이 상선이다** — 3~8호선(오름차순 = 하선)과 반대다. CSV 실물에서 오름차순
468행이 전부 상선, 내림차순 468행이 전부 하선으로 갈린다.

## 스키마 변경

`V9__widen_congestion_pred_predictor_version.sql` — `predictor_version` `VARCHAR(32)` → `VARCHAR(128)`.

V7(통지 04 1.2절 DDL)이 32로 잡혀 있었는데 실값이 67자다.

```
lightgbm:festival_selflag_d1sd_d7_resid_masked-stack_train2024-2025   (67자)
lookup:line9_2025_2026                                               (22자)
```

첫 행부터 `value too long for type character varying(32)` 로 죽는다. V2 가 `edge_time.source`(8→16)에서
겪은 것과 같은 종류다. 값이 "예측기:피처조합-학습기간" 구조라 피처가 늘면 그대로 길어져 여유를 뒀고,
그래도 넘으면 로더 검증기가 적재 전에 먼저 막는다(`MasterValidator.validateCongestionPred`).

`pred_source` 는 넓히지 않았다 — 최대 15자(`lookup_negative`)로 32 안에 든다. 다만 V7 주석이 2종만
적고 있어 3종(`lookup_line9` 포함)으로 고쳤다. **제약이 아니라 주석이라 값은 이미 들어간다.**

## 데이터 흐름

```
AI 워커 j15a104a serving/ ─(crowdpred-fetch.mjs: 기준일 이후 전부 동기화)─▶ AI/data/CROWD/serving/*.csv + .meta.json
                                                    │
                                                    ▼
                  CsvCongestionPredSource (날짜별 generated_at 최신 회차 · 사이드카 필수 · 행 수 대조)
                                                    │
                                                    ▼
                          CongestionPredParser (역번호·노선 매핑 · 스케일 · 결측 보존)
                                                    │
                                                    ▼
              MasterValidator.validateCongestionPred (키 중복 · 범위 · 길이 · 마스터 대조)
                                                    │
                                                    ▼
                          UpsertWriter.upsertCongestionPred (멱등)
```

## 읽는 쪽에 미치는 영향

`RouteSearchService.congestionPredLookup()` 이 이 표를 읽어 혼잡 회피 경로를 고른다(158, 인웅).
표가 비어 있던 동안은 조회가 전부 결측으로 빠져 노선 평균(`WEEKDAY_AVERAGE`)으로 폴백했고, 이 적재로
링크 예측(`RECENT_7D`)이 나온다. 조회가 매 요청 DB 를 읽어 **`be` 재시작 없이 즉시 반영**된다.

**조회 키에서 `direction` 을 빼자고 제안해 두었다**(`.claude/handoff/TO_ROUTE-subway-direction-02.md`).
`from→to` 가 이미 방향 있는 링크라 `direction` 은 중복 정보이고, 그것을 키로 쓰면 9호선·2호선 지선·
반전 링크 3개에서 조회가 어긋난다. **적재는 어느 쪽이든 CSV 값을 그대로 넣으므로 영향이 없다.**
ROUTE 확정 전이다(AI 계약서엔 결정으로 적혔다 — 회신에서 바로잡는다).

## 테스트

```bash
./gradlew test --offline --rerun --tests 'com.ssafy.s15p21a104.load.crowdpred.*'
node --test "BE/scripts/data/test/crowdpred-fetch.test.mjs"
```

파서 12 · 검증 12 · 원천 11 · 스크립트 9. 입력은 실제 conf 표와 AI 에게 받은 실물 278행 샘플
(`docs/external/samples/predictions_2026-09-20_278rows.csv`)이다 — 역번호 체계나 열 구성이 바뀌면
인라인 픽스처가 아니라 거기서 먼저 깨지게 했다. 하루치 전체(21,684행)는 커밋하지 않는다.

304 에서 더한 것: 원천 `304-S1`(파일명은 뒤지만 `generated_at` 은 앞인 두 회차 → `generated_at` 이 이긴다),
스크립트 `artifactsSince`(2일치 전부 · 기준일 이전 제외 · 같은 날짜 여러 회차 전부 · 비산출물 제외).

## 남은 일 (후속)

- **타이머 첫 자동 발화 확인** — 09-21 파일은 15:31 KST 수동 실행분이다. 타이머는 09-22 09:31 KST 에 처음
  돈다. 그날 `--list` 로 09-22 재생성분과 09-23 신규가 보이는지, 로더가 09-22 는 새 회차를 고르는지 본다
  (AI 도 같이 본다, 통지 08).
- 매일 적재 자동화 — 지금은 받기·적재 모두 수동이다.
- `generated_at` 을 파일별로 기록(위 "값 규칙").
- ROUTE 조회 키에서 `direction` 제거 여부(위).
- AI 에 파일명에 생성 일시(UTC)를 넣어 달라고 제안(비차단 — 지금은 우리 쪽에서 사이드카로 흡수한다).
