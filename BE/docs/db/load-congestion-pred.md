# 혼잡도 예측 정적 적재 (S15P21A104-305)

AI CROWD 배치가 만든 링크 단위 혼잡도 예측을 `congestion_pred` 에 넣는다. **AI 는 PG 에 직접 쓰지 않고
BE load job 이 넣는다** — 회신 04 L-2 에서 확정한 구조이고 172(`bike_stock_pred`)와 같다.

## 실행

```bash
# 1) 최신 산출물 받기 (AI EC2 → AI/data/CROWD/serving/)
node BE/scripts/data/crowdpred-fetch.mjs

# 2) 적재
cd BE && SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun \
  --args='--load.sources=crowdpred --load.dry-run=true'   # 파싱·검증·건수만
cd BE && SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun \
  --args='--load.sources=crowdpred'                       # 실제 적재
```

`crowdpred` 는 기본 `sources` 목록에 **없다.** 원천 파일을 먼저 받아야 하므로 기본에 넣으면 파일이 없는
팀원의 전체 적재가 실패한다(`bikepred` 와 같은 이유).

> **2026-09-21 기준 1)이 실패한다.** AI 배치(`crowd-batch-predict.timer`)가 서버에 아직 배포되지 않아
> 원격 폴더 자체가 없다(통지 07 C-5 로 확인 요청함). 그전까지는 받은 파일을
> `AI/data/CROWD/serving/` 에 직접 두고 2)만 실행한다.

## 원천

| | |
| --- | --- |
| 만드는 곳 | AI CROWD 배치 `batch_predict --link-table` (매일 09:30 KST, 오늘·내일 2일치) |
| 서버 경로 | `~/Soomgil-INFRA-ai-data-monitoring/AI/data/CROWD/serving/` |
| 파일 | `predictions_<YYYY-MM-DD>_<HHMMSS>.csv` + **사이드카** `.meta.json` |
| 계약 | `AI/app/CROWD/SERVING_CONTRACT.md` 8·8.1·8.2절 · 통지 07 |
| 하루치 | 21,684행 · 링크 556 · 역 286 · 2.9 MB (2026-09-20 실측) |

열 10개는 순서까지 회신 04 6.1절에서 확정했다.

```
pred_date, line, from_station_no, to_station_no, direction, time_slot, level, data_status, pred_source, predictor_version
```

사이드카는 키가 셋뿐이다. **필수다** — `generated_at` 이 `congestion_pred` 의 NOT NULL 열이고 행 수
대조에 쓴다.

```json
{"target_date": "2026-09-20", "row_count": 21684, "generated_at": "2026-09-20T23:43:00+09:00"}
```

## 값 규칙

- **`level` 은 NULL 을 허용하고 상한이 없다.** 빈 칸은 그대로 NULL 이다 — 0 으로 채우면 "혼잡도 0%" 와
  "모른다" 가 섞인다. 이유는 `data_status` 가 따로 말한다. 100 을 넘는 값도 그대로 넣는다(실측 최대 164.4).
- **`direction` 은 원천 값을 그대로 넣는다.** 2호선이라도 지선 구간은 내선/외선이 아니라 상선/하선으로
  온다. 역번호 순서로 재추론하지 않는다 — `from→to` 가 이미 방향 있는 링크다.
- **`time_slot` 이 48개가 다 오지 않는다.** 운행 없는 새벽(2~10)은 행 자체가 없어 실측 39종이다.
  "48 × 링크 수" 로 가정하면 어긋난다.
- **한 번 돌 때 날짜가 다른 파일이 둘 생긴다.** 배치 기본이 `--today --tomorrow` 라 오늘·내일
  2일치를 따로 쓴다. 그래서 로더는 **대상 날짜마다 최신 회차 하나씩을 골라 모두 읽는다** —
  파일명만 정렬해 하나만 고르면 내일 것만 잡히고, 조회는 `pred_date = 오늘` 로 하므로 화면이 빈다.
  같은 날짜가 여러 번 만들어졌으면 그중 가장 늦은 회차만 쓴다.
- **`generated_at` 은 산출 시각, `updated_at` 은 적재 시각이다.** 재적재 판정 근거라 구분한다.
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

## 2026-09-20 적재 결과 (로컬 postgres:16)

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

멱등성: 같은 파일을 다시 적재해도 21,684행 그대로(660 ms).

### 2일치 확인

배치가 실제로 내놓을 모양(오늘·내일 파일 2개 + 같은 날짜 재생성분 1개)을 만들어 돌렸다.

```
원천 43368 행 · 날짜 [2026-09-20, 2026-09-21] · 링크 556 · 슬롯 39종 · 건너뜀 0
적재 congestion_pred · 43368 행 · 1036 ms · 41861 행/초
```

| `pred_date` | 행 |
| --- | --- |
| 2026-09-20 | 21,684 |
| 2026-09-21 | 21,684 |

날짜별로 최신 회차 하나씩만 골라 두 날짜가 다 들어갔다 — 09-20 은 `_234300`(재생성분)이 쓰이고
`_093000` 은 무시된다.

## 9호선

AI 가 9호선 2·3단계 13역(언주 4126 ~ 중앙보훈병원 4138)을 편입해 하루 936행이 새로 들어온다.
`pred_source=lookup_line9` 이고 `predictor_version` 도 `lookup:line9_2025_2026` 으로 다르다 —
모델을 타지 않고 기준선만 쓴다. 9호선은 전날 승하차 원천이 없어(열린데이터광장 `getStnPsgr` 가
1~8호선만 준다) 모델 입력 13개 중 6개가 죽기 때문이다(통지 07 3절).

**9호선은 역번호 오름차순이 상선이다** — 3~8호선(오름차순 = 하선)과 반대다. CSV 실물에서 오름차순
468행이 전부 상선, 내림차순 468행이 전부 하선으로 갈린다.

## 스키마 변경

`V8__widen_congestion_pred_predictor_version.sql` — `predictor_version` `VARCHAR(32)` → `VARCHAR(128)`.

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
AI EC2 serving/ ─(crowdpred-fetch.mjs)─▶ AI/data/CROWD/serving/*.csv + .meta.json
                                                    │
                                                    ▼
                          CsvCongestionPredSource (최신 파일 선택 · 사이드카 필수 · 행 수 대조)
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
표가 비어 있던 동안은 조회가 전부 결측으로 빠졌고, 이 적재로 값이 생긴다.

**조회 키에서 `direction` 을 빼자고 제안해 두었다**(`.claude/handoff/TO_ROUTE-subway-direction-02.md`).
`from→to` 가 이미 방향 있는 링크라 `direction` 은 중복 정보이고, 그것을 키로 쓰면 9호선·2호선 지선·
반전 링크 3개에서 조회가 어긋난다. **적재는 어느 쪽이든 CSV 값을 그대로 넣으므로 영향이 없다.**

## 테스트

```bash
./gradlew test --offline --rerun --tests 'com.ssafy.s15p21a104.load.crowdpred.*' --tests '*MasterValidator*'
node --test "BE/scripts/data/test/crowdpred-fetch.test.mjs"
```

파서 12 · 검증 12 · 원천 8 · 스크립트 8. 입력은 실제 conf 표와 AI 에게 받은 실물 278행 샘플
(`docs/external/samples/predictions_2026-09-20_278rows.csv`)이다 — 역번호 체계나 열 구성이 바뀌면
인라인 픽스처가 아니라 거기서 먼저 깨지게 했다. 하루치 전체(21,684행)는 커밋하지 않는다.

## 남은 일 (후속)

- **AI 배치 서버 배포**(통지 07 C-5). 그전까지는 매일 갱신되지 않고 2026-09-20 데이터가 고정이다.
- prod 적재 — MR 병합 후 터널로. `load-prod.md` 절차.
- ROUTE 조회 키에서 `direction` 제거 여부(위).
