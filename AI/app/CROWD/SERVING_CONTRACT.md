# CROWD 혼잡도 — 서빙 산출물·API 명세 (BE 전달용)

작성 2026-09-16 · 기준 브랜치 `feat/CROWD-serving-output-contract`(197 A·B·C부 반영) · 확인한 실제 산출물 `data/CROWD/serving/predictions_2026-09-13/14.parquet`(2026-09-17 15:24 재생성 — 200 2024-25 최종 fit 반영판)

> **이 문서는 프로덕션 출력의 계약이다. 아래가 바뀌면 같은 커밋에서 이 문서를 고친다.**
> `batch_predict.OUTPUT_COLS`·`TRAIN_OUTPUT_COLS` · `schemas.py`의 응답 모델 · `data_status` 값 ·
> 등급 임계값(`crowd_grade_thresholds`) · 예측기 계열 추가·교체 · 배율표 판 교체 · API 경로·파라미터.
> 모델 성능·피처 세트는 이 문서가 아니라 `pipeline/MODEL_REGISTRY.md`에 적는다.
>
> **이 문서는 테스트가 강제한다**(197 C부). `test/CROWD/test_crowd_serving_contract.py`가 1절 컬럼 표·
> 2절 상태 표·3절 메타 표·4절 경로·파라미터·응답 예시·7절 열차 표 컬럼을 각각 `OUTPUT_COLS`·
> `DATA_STATUS_VALUES`·`META_KEYS`·OpenAPI·`schemas.py`·`TRAIN_OUTPUT_COLS`와 대조한다. 코드만
> 고치면 CI가 막힌다.
>
> **테스트가 못 막는 것 — 사람이 챙긴다.** 아래 셋은 리포 밖이거나 값이라서 CI가 잡지 못한다.
> 1. **예시 값**(1절 실제 2행, 4절 응답 JSON) — 테스트는 키와 타입만 보고 값은 안 본다. **배치를
>    재생성하면 같이 갱신한다.** 실제로 197에서 4절 예시가 라우팅 이전 값으로 남아 있었다.
> 2. **Notion 프로덕션 페이지**(실험실 / 혼잡도 프로덕션 / 서빙 출력·API 입출력 명세) — 이 문서의 사본이다.
> 3. **BE 통지문** — 컬럼·필드가 바뀌면 `.claude/handoff/TO_BE-crowd-contract-change-NN.md`로 알린다.

AI는 **요청 시점에 모델을 돌리지 않는다.** 하루 1회 배치가 날짜별 예측 표를 만들고, API는 그 표만 읽는다.

```
배치(batch_predict.py) → data/CROWD/serving/predictions_YYYY-MM-DD.parquet + .meta.json
                       → GET /crowd/... 가 이 파일만 조회
```

---

## 0. 먼저 읽을 것 — 지금 상태에서 BE가 조심할 것 3가지

| # | 내용 | BE 조치 |
| --- | --- | --- |
| 1 | **(수정됨, 197)** `boarding_pred`·`alighting_pred`는 이제 항상 0 이상이다 — 등급 계산이 쓰는 대체 값과 같은 값이 출력에 실린다. 음수가 났던 셀(과거 3,744행/17.3%, 최솟값 −457.9명이었던 원인)은 lookup 값으로 대체되고(둘 다 없으면 0), 그 사실은 새 컬럼 `pred_source`(str: `model`/`lookup_negative`)로 식별한다 | 인원 필드를 그대로 노출해도 된다. 정확도를 다르게 표시하고 싶으면 `pred_source="lookup_negative"`인 셀만 구분 표시. 아래 5.1절 참고 |
| 2 | **`boarding_pred`는 1시간 값이고, 30분 행 2개에 같은 값이 중복된다.** 승하차 예측은 1시간 단위이고 30분 분해는 혼잡도(`congestion_pct`)에만 적용된다 | **절대 합산하지 말 것.** `06:00`과 `06:30` 행의 `boarding_pred`를 더하면 2배가 된다 |
| 3 | **현재 운영이 이력 결손 상태다.** 2026-09-13 메타가 `lag1d_available: false` — 전날 실측이 없어 1주 전 시차만으로 예측됐다. 옛 LightGBM 판에서 `lookup_substituted_rows`가 3,744(17.3%)까지 갔던 이유다 — B부 라우팅이 이 상태를 GRU로 넘기면서 **228행(1.06%)**으로 줄었다. 145 후속부터는 이 `d7_only` 상태를 마스킹 학습 LightGBM이 맡는다(`masking-check/RESULTS.md` 14절) | `meta.lag1d_available`이 `false`면 화면에 정확도 주의 표시를 붙일 수 있게 준비. API `StationCongestionResponse.lag1d_available`로 내려간다 |

---

## 1. 배치 산출물 — parquet

경로: `AI/data/CROWD/serving/predictions_{YYYY-MM-DD}.parquet`
크기: 1일치 **21,606행** (역 × 20슬롯 × 방향 × 30분 2슬롯)

| 컬럼 | 타입 | 의미 | null 가능 |
| --- | --- | --- | --- |
| `date` | datetime64[us] | 대상 날짜(자정) | 없음 |
| `station_no` | int64 | 역번호(서울시 표준) | 없음 |
| `station_name` | str | 역명 | 있음 |
| `line` | str | 호선(`"1호선"` 형식) | 있음 |
| `direction` | str | `상선` / `하선` / `내선` / `외선`(2호선) | 없음 |
| `time_slot_30min` | str | 30분 슬롯 시작 시각, `"08:30"` | 없음 |
| `time_slot` | str | 원천 1시간 슬롯, `"08-09"`. 첫 슬롯 `"~06"`, 마지막 `"24~"` | 없음 |
| `congestion_pct` | float64 | **보정 혼잡도(%)**, 정원 100% 기준 | **있음** — 배율표 결측 |
| `grade` | float64 | 등급 `0.0`/`1.0`/`2.0`. parquet에서는 **float**이고(NaN을 담기 위해) **API는 int로 변환해 내려준다** | **있음** |
| `data_status` | str | 셀 상태, 2절 | 없음 |
| `boarding_pred` | float64 | 승차 예측(명), **1시간 값**. 0 미만은 lookup 값으로 대체됨(197) | 있음 |
| `alighting_pred` | float64 | 하차 예측(명), **1시간 값**. 0 미만은 lookup 값으로 대체됨(197) | 있음 |
| `pred_source` | str | `model`(정상) / `lookup_negative`(그 슬롯의 승차·하차 예측 중 하나라도 음수라 lookup 값으로 대체됨, 197) | 없음 |
| `boarding_lookup` | float64 | 기준선(요일유형×역×시간대 평균) 승차 | 있음 |
| `alighting_lookup` | float64 | 기준선 하차 | 있음 |
| `actual_boarding` | float64 | 실측 승차 — **과거 날짜만** 채워짐 | 있음 |
| `actual_alighting` | float64 | 실측 하차 — 과거 날짜만 | 있음 |
| `train_capacity` | int64 | 편성 정원(명). 혼잡도 분모 | 없음 |

### 실제 2행

```json
[
 {
  "date": "2026-09-14T00:00:00.000",
  "station_no": 150,
  "station_name": "서울역",
  "line": "1호선",
  "direction": "하선",
  "time_slot_30min": "06:00",
  "time_slot": "06-07",
  "congestion_pct": 14.043068,
  "grade": 0.0,
  "data_status": "ok",
  "boarding_pred": 1380.633132,
  "alighting_pred": 2441.109924,
  "pred_source": "model",
  "boarding_lookup": 542.6489795918,
  "alighting_lookup": 2115.8204081633,
  "actual_boarding": null,
  "actual_alighting": null,
  "train_capacity": 1600
 },
 {
  "date": "2026-09-14T00:00:00.000",
  "station_no": 150,
  "station_name": "서울역",
  "line": "1호선",
  "direction": "하선",
  "time_slot_30min": "06:30",
  "time_slot": "06-07",
  "congestion_pct": 22.342685,
  "grade": 0.0,
  "data_status": "ok",
  "boarding_pred": 1380.633132,
  "alighting_pred": 2441.109924,
  "pred_source": "model",
  "boarding_lookup": 542.6489795918,
  "alighting_lookup": 2115.8204081633,
  "actual_boarding": null,
  "actual_alighting": null,
  "train_capacity": 1600
 }
]
```

두 행의 `boarding_pred`가 **같다**(1380.63). 0절 2번이 말하는 지점이다. `congestion_pct`는 14.0 → 22.3로 30분마다 다르다.

---

## 2. `data_status` — 값을 채우지 않고 상태로 알린다

숫자를 낼 수 없는 셀은 **`null`로 두고 이유를 남긴다**(팀 원칙 8: 표본 부족 구간에 값을 채우지 않는다). BE·FE는 이 셀을 "데이터 부족"으로 표시하고, **임의로 0이나 이웃 값으로 채우지 말 것.**

| 값 | 의미 | `congestion_pct` | 화면 처리 |
| --- | --- | --- | --- |
| `ok` | 정상 | 있음 | 정상 표출 |
| `calibration_fallback` | 1~8호선 공휴일이라 **일요일 배율**을 빌려 씀 | 있음 | 값은 쓰되 "공휴일 추정" 구분 표시 권장 |
| `segment_truncated` | 절단 구간 종점 링크(코레일·인천교통공사 직결 구간이 원천에 없음). 재차인원이 구조적으로 0 | 없음 | "해당 없음" |
| `no_calibration` | 그 밖의 배율표 결측(결번 역, 미대응 2호선 지선) | 없음 | "데이터 부족" |
| `no_lookup` | 기준선 자체가 없음(학습 구간에 없는 요일유형×역×시간대) | 없음 | "데이터 부족" |
| `no_data` | **API 전용** — 그 날짜 표가 아직 없음(배치 미실행) | — | 404로 내려감 |

2026-09-13 실측 분포(197 재생성판): `ok` 20,892 / `no_calibration` 585 / `segment_truncated` 129 → **결측 714행 = 3.3%**. 199의 절단면 경계 유입 반영으로 이전 판(1,443행 = 6.7%)보다 절반 이하로 줄었다.

### 등급 임계값

`grade`는 `congestion_pct`를 임계값으로 자른 값이고, 임계값은 **설정에서 온다**(`crowd_grade_thresholds`, 현재 `"50,100"`).

| grade | 범위 | 뜻 |
| --- | --- | --- |
| `0` | < 50% | 여유 |
| `1` | 50% ≤ x < 100% | 보통 |
| `2` | ≥ 100% | 혼잡 |

**임계값을 BE에 하드코딩하지 말 것.** `GET /crowd/meta`의 `grade_thresholds`를 읽어 쓴다 — 바뀔 수 있다(국토부 고시의 150/170/190은 우리 타깃 분포에서 판별력이 없어 50/100을 쓰고 있다).

---

## 3. 배치 메타 — `.meta.json`

경로: `predictions_{YYYY-MM-DD}.meta.json`. 표가 **어떤 조건으로 만들어졌는지**를 담는다. 운영 모니터링·화면 주의문구의 근거다. 메타 키는 **28개**다(197까지 21개 + 200에서 이벤트 커버리지 2개 추가 + 239에서 열차·노드 표 관련 5개 추가).

| 키 | 예시 | 의미 |
| --- | --- | --- |
| `target_date` | `"2026-09-13"` | 대상 날짜 |
| `in_panel` | `false` | 그 날짜가 학습 패널에 있는지(과거 재현 여부). `false`면 실운영 예측 |
| `history_window_days` | `7` | 이력 창 길이 — 예측기에 따라 7 또는 14다(LightGBM·lookup은 7, DL은 14 — `Predictor.required_history_days`) |
| `history_days_present` | `6` | 실제로 확보된 이력 일수 |
| `history_dates` | `["2026-09-06", …]` | 확보된 이력 날짜 |
| **`lag1d_available`** | **`false`** | **전날 실측 유무. `false`면 정확도 저하** |
| `lag7d_available` | `true` | 1주 전 실측 유무 |
| `availability` | `"d7_only"` | (197) 가용성 판정 — `full`/`d1_only`/`d7_only`/`no_lag`. `routing.availability()`가 `lag1d_available`·`lag7d_available`로 정한다 |
| `routing_rule` | `{"pred": "lightgbm", "avail": "d7_only", "line": null, "day_type": null, "group": null}` | (197, 145 후속) 그 kind를 고른 라우팅 규칙(`routing.describe_policy`). `predictor_override=true`면 `null` |
| `predictor` | `"lightgbm"` | 쓰인 예측기 종류. **라우팅 결과라 날짜마다 다를 수 있다**(197 B부, 145 후속) |
| `predictor_version` | `"lightgbm:festival_selflag_d1sd_d7_resid_masked-stack_train2024-2025"` | 아티팩트까지 포함한 버전 |
| `predictor_override` | `false` | (197) `--predictor` CLI로 kind를 명시해 라우팅을 건너뛰었는지 |
| `predictor_fallback` | `null` | **(197부터 항상 `null`)** 옛 "이력 전무 시 lookup 강제 대체" 의미는 없어졌다 — 필드는 BE 계약 유지를 위해 키만 남는다 |
| `recent_dates_available` | `[…]` | D−1 수집기가 쌓은 최근 실측 날짜 |
| `events_coverage_end` | `"2026-12-27"` | (200) `crowd_events_files`에 나열된 이벤트 표들을 합친 최대 date. 읽은 표가 하나도 없으면 `null` |
| `events_available` | `true` | (200) `target_date`가 `events_coverage_end` 이내인지. `false`면 그 날짜의 경기·축제 칸은 "없었다"가 아니라 "표가 안 덮는다"는 뜻(0-채움 자체는 유지) |
| `grade_thresholds` | `[50.0, 100.0]` | 등급 임계값 |
| `rows` | `21606` | 표 행 수 |
| `status_counts` | `{"ok": 20892, "no_calibration": 585, "segment_truncated": 129}` | 상태별 행 수 |
| `lookup_substituted_rows` | `334` | (197, 옛 `clipped_rows`) `pred_source="lookup_negative"`인 행 수 |
| `holiday_calendar_until` | `"2035-10-02"` | 공휴일 달력 커버 종료일 |
| `topology_gaps` | `[…]` | 노선 토폴로지 결번 구간 |
| `train_table` | `false` | (239) 열차·노드 표(`predictions_train_{date}.parquet`, 7절)를 이번에 만들었는지. 기본 `false`(설정값 `crowd_train_table`, CLI `--trains`/`--no-trains`로 이번 실행만 덮어쓸 수 있다) |
| `timetable_version` | `"timetable_long.parquet@2026-09-11"` | (239) 시각표 interim 파일 버전(`파일명@수정일`, 135 파서 산출물엔 버전 컬럼이 없어 파일 mtime을 쓴다). `train_table=false`면 `null` |
| `train_rows` | `105470` | (239) 열차·노드 표 행 수. `train_table=false`면 `null` |
| `headway_long_rows` | `4279` | (239) 배차 간격이 `long_headway_min`(12분)을 넘어 균등 도착 가정이 약해진 채 배분된 열차 행 수. `train_table=false`면 `null` |
| `train_mass_gap` | `3.6e-12` | (239) 슬롯 재차인원 합과 열차 배분 합의 최대 절대오차(질량 보존 확인, 7절). `train_table=false`면 `null` |
| `generated_at` | `"2026-09-17T15:24:24+09:00"` | 생성 시각(KST, ISO8601 오프셋 포함) |

---

## 4. 조회 API — 3종

prefix `/crowd`. 로직은 `service.py`, 응답 모델은 `schemas.py`.

### 4.1 `GET /crowd/meta`

가용 날짜·임계값·모델 버전. **BE 시작 시 1회 읽어 캐시할 값들이다.**

```json
{
  "available_dates": ["2026-09-13", "2026-09-14"],
  "grade_thresholds": [50.0, 100.0],
  "predictor": "lightgbm",
  "predictor_version": "lightgbm:festival_selflag_d1sd_d7_resid_masked-stack_train2024-2025",
  "generated_at": "2026-09-17T15:24:24+09:00",
  "status_counts": {"ok": 20902, "no_calibration": 585, "segment_truncated": 119},
  "topology_gaps": [{"line": "3호선", "segment": "본선", "missing": [321]}],
  "events_coverage_end": "2026-12-27",
  "events_available": true
}
```

### 4.2 `GET /crowd/stations/{station_no}/congestion`

| 파라미터 | 필수 | 설명 |
| --- | --- | --- |
| `station_no` (path) | O | 역번호 |
| `date` (query) | O | `YYYY-MM-DD` |
| `direction` (query) | X | `상선`/`하선`/`내선`/`외선`. 생략 시 전부 |

```json
{
  "date": "2026-09-13",
  "station_no": 150,
  "station_name": "서울역",
  "line": "1호선",
  "train_capacity": 1600,
  "predictor_version": "lightgbm:festival_selflag_d1sd_d7_resid_masked-stack_train2024-2025",
  "lag1d_available": false,
  "slots": [
    {"time_slot_30min": "06:00", "direction": "하선", "congestion_pct": 7.534097, "grade": 0, "data_status": "ok", "pred_source": "model"},
    {"time_slot_30min": "06:30", "direction": "하선", "congestion_pct": 5.658234, "grade": 0, "data_status": "ok", "pred_source": "model"}
  ]
}
```

`slots[].congestion_pct`·`grade`는 **`null`일 수 있다**(2절).

### 4.3 `GET /crowd/lines/{line}/congestion`

노선 한 개의 특정 30분 시점 스냅샷.

| 파라미터 | 필수 | 설명 |
| --- | --- | --- |
| `line` (path) | O | `1호선` 등 |
| `date` (query) | O | `YYYY-MM-DD` |
| `time` (query) | O | 30분 슬롯 시작, `08:30` (**쿼리 키가 `time`이다**, 응답 키는 `time_slot_30min`) |

```json
{
  "date": "2026-09-13",
  "line": "2호선",
  "time_slot_30min": "08:30",
  "stations": [
    {"station_no": 201, "station_name": "시청", "direction": "내선", "congestion_pct": 27.087917, "grade": 0, "data_status": "ok", "pred_source": "model"}
  ]
}
```

### 4.4 에러 규약

| 상황 | 응답 |
| --- | --- |
| **그 날짜 표가 없음**(배치 미실행) | **404** — `{"detail": "2026-09-20 예측 표가 없다 — 배치 미실행 (GET /crowd/meta 참고)"}` |
| **존재하지 않는 역** | **200** + `slots: []` (역 목록은 BE가 관리) |

이 둘을 구분한 의도는 **"데이터가 아직 없다"와 "그런 역이 없다"를 BE가 다르게 처리**할 수 있게 하려는 것이다.

---

## 5. 알려진 결함

### 5.1 인원 예측 음수 유출 (해결됨, S15P21A104-197)

- **발견 당시 현상**: `boarding_pred`·`alighting_pred`가 음수로 내려갔다. 2026-09-13 표에서 **17.3%(3,744행)**, 최솟값 **−457.9명**. 그중 **3,194행은 `data_status="ok"`**라 상태값으로 감지 불가했다. 당시 메타는 `lag1d_available: false`(전날 실측 없음)인 이력 결손 상태였다 — 잔차 예측이 크게 흔들려 음수 비율이 높았던 배경이다(이력이 완비되면 2025 평가 전체 기준 0.47%로 낮다).
- **원인**: 배치가 재귀식 입력에는 0 클립을 적용하면서(`to_congestion_table`) 출력 표의 `*_pred` 컬럼은 **클립 전 원본을 그대로 실었다**. 같은 행에서 `boarding_pred < 0`인데 `congestion_pct`는 0을 넣고 계산한 값이라 표 내부가 불일치했다.
- **수정 1단계(A부)**: `to_congestion_table`이 재귀식 입력용으로 만든 클립(0 하한) 값을 출력 `boarding_pred`·`alighting_pred`에도 그대로 재사용해 표 내부 불일치를 없앴다. 클립이 일어난 행은 `pred_clipped`(bool)로 노출했다.
- **수정 2단계(B부, 197 B-2) — 음수 셀은 0 클립이 아니라 lookup 대체**: 145 `family-check/RESULTS.md` 7절에서 **모델이 음수를 낸 셀은 lookup이 더 정확하다**는 게 드러났다 — 0 클립 후 RMSE 대비 lookup RMSE가 `no_lag` **90.46 → 69.85**, `d7_only` **53.86 → 27.18**로 낮다. 그래서 음수 셀은 그 타깃의 `{target}_lookup` 값으로 대체하고, lookup도 없거나(NaN) 음수면 그때만 0을 최종 하한으로 쓴다. `pred_clipped`(bool)는 **`pred_source`**(str: `model`/`lookup_negative`)로 교체됐다 — 대체가 일어났는지뿐 아니라 무엇으로 대체됐는지(모델 그대로인지)까지 구분한다.
- **BE 영향**: 인원 필드를 그대로 노출해도 된다(더 이상 `max(0, x)` 방어 불필요). `pred_source="lookup_negative"`인 셀은 원한다면 "예측 보정됨" 등으로 구분 표시할 수 있다. `congestion_pct`·`grade`는 A부 수정 전후로 값이 바뀌지 않았지만(이미 클립된 값으로 계산돼 있었다), **B부(lookup 대체)는 그 셀들의 `congestion_pct`·`grade`를 다시 바꾼다** — 0이 아니라 lookup 값으로 재귀식을 계산하기 때문이다.

### 5.2 구 모델로 만들어진 잔존 파일 (해소됨, 2026-09-16 재생성)

`predictions_2026-09-14.parquet`이 한때 구 모델(`festival_selflag_d1d7_resid_20260911-1533`)로 만들어진 채 남아 있었다. 197 B부 재생성으로 두 날짜 모두 현재 라우팅 결과(`dl:dl_gru_s14_noev_s42_20260914-1358`)로 갱신됐다.

→ **BE는 `meta.predictor_version`을 로깅해 두는 게 좋다.** 표마다 모델이 다를 수 있고, 이제는 **가용성에 따라 실제로 달라진다**(197 B부).

### 5.3 아티팩트 이름 정렬 함정 (조치됨)

`latest_artifact`는 이름 정렬로 최신을 고르는데, DL 변형 18개 중 이름이 가장 큰 `dl_lstm_s14_noev_s44`가 뽑혔다 — 채택된 모델은 `dl_gru_s14_noev_s42`다. 배포 아티팩트를 설정값(`crowd_dl_artifact`)으로 고정해 막았다. **DL 아티팩트를 새로 학습해 교체할 때는 이 설정값을 같이 고쳐야 한다.**

145 후속부터는 LightGBM 배포판도 같은 이유로 고정한다 — `crowd_lgbm_artifact`(`app/core/config.py`)가 마스킹 학습 아티팩트를 이름으로 못박는다(145 후속 `…_masked-stack_20260917-1113` → 200에서 2024+2025 최종 fit `…_masked-stack_train2024-2025`로 교체, DL도 `dl_gru_s14_noev_s42_train2024-2025`로 교체. 승격 절차는 `MODEL_REGISTRY.md` 4b). 지금은 이름 정렬로도 우연히 이 폴더가 최신이지만, 다음 학습이 그보다 이름이 앞서는 폴더를 만들면 `auto`가 조용히 옛 아티팩트로 돌아간다 — 그래서 운에 맡기지 않는다.

### 5.4 강동(5호선) 행 중복 — `(station_no, direction, time_slot_30min)`은 유일 키가 아니다 (미해결, 티켓 필요)

145 후속 드리프트 측정 중 발견(2026-09-17). 강동은 5호선 본선의 종점이자 하남선의 첫 역이라 토폴로지에서 **링크가 2개** 잡히고,
표에는 30분 셀마다 강동 행이 **2개**(하루 234행 = 117셀 × 2) 실린다. 두 행의 값은 다르다 — 한쪽은 본선 종점이라 재차 0(`congestion_pct` 0),
다른 쪽은 하남선 방향의 실제 재차(예: 168.8%). 다른 272역은 유일하다. 197 계약이 이 사실을 적지 않았다(AI 측 누락).

| 영향 | 지금 할 것 | 고칠 방향 |
| --- | --- | --- |
| 세 필드로 map을 만들면 강동은 나중 행이 앞 행을 덮는다(어느 쪽이 남는지 순서 운). 두 행을 합산하면 2배 | BE: 강동만 두 행이 온다고 알고 처리(합산 금지, `max` 또는 두 값 표시). AI: 이 절과 통지문 02 4절로 알림 | (a) 링크 식별 컬럼(`segment` 또는 `from_station_no`/`to_station_no`)을 추가해 키를 유일하게 — 정보를 안 버림(권고) / (b) 강동을 한 행으로 접음. BE 선호 회수 후 별도 티켓. 컬럼이 늘면 1절 표·`OUTPUT_COLS`·계약 테스트가 같이 바뀐다 |

---

## 6. 이번 검증(S15P21A104-145)이 만든 변경

**145 본 검증에서는 실행되는 프로덕션 코드 변경이 없었다.** 145는 검증 티켓이고, 18개 변경 파일 중 `app/` 아래는 문서 1건뿐이었다. **145 후속(마스킹 학습, 2026-09-17)은 예외다** — `routing.POLICY`·`config.crowd_lgbm_artifact`·`batch_predict.resolve_predictor`를 바꿨고, 그 영향은 아래 표 마지막 행에 있다.

| 경로 | 성격 |
| --- | --- |
| `app/CROWD/pipeline/MODEL_REGISTRY.md` (+17/−3) | **문서** — 가용성별 예측기 선택 판정표 추가 |
| `test/CROWD/test_crowd_stat_models.py` | 테스트 |
| `validation/CROWD/{stat-model,family,split-tuning}-check/*` | 검증 스크립트·결과·노트북 |

즉 **BE가 지금 당장 바꿔야 할 것은 없다.** 다만 145가 5.1 결함과 아래 후속을 드러냈다.

### BE에 영향이 갈 후속 예정

| 항목 | 내용 | BE 영향 |
| --- | --- | --- |
| 인원 음수 수정(5.1) | `*_pred` 클립 → lookup 대체 + `pred_clipped`(bool) → `pred_source`(str) 컬럼 교체 | **컬럼 1개 이름·타입 변경** — parquet 스키마·API 응답 반영 완료(197 B부) |
| 가용성별 라우팅(197) | 이력 완비(`full`)는 LightGBM, 결손·전무(`d1_only`/`d7_only`/`no_lag`)는 GRU(`dl`)로 라우팅 | `meta.predictor`·`predictor_version` 값이 날짜마다 달라진다(이미 내려가는 필드, 스키마 변경 없음). `meta.availability`·`routing_rule`·`predictor_override` 3개 키가 새로 추가됐다 |
| **가용성별 라우팅 수정(145 후속, 마스킹 LightGBM)** | `d7_only`·`no_lag`는 이제 LightGBM(마스킹 학습 아티팩트, `masking-check/RESULTS.md` 14절)이 맡는다. `d1_only`만 GRU(`dl`)로 남는다 | 스키마·키는 그대로다(변경 없음). `predictor_version`의 LightGBM 값이 `lightgbm:festival_selflag_d1sd_d7_resid_masked-stack_train2024-2025`로 바뀐다 — `d7_only`·`no_lag` 날짜의 표시 모델명이 GRU에서 LightGBM으로 보인다. **값 드리프트**(2026-09-13/14 `d7_only` 두 날짜를 GRU 판 → 마스킹 LightGBM 판으로 재생성해 21,606행씩 행 정렬 비교): `congestion_pct` 평균 \|Δ\| **0.62 / 0.86%p**(중앙값 0.39 / 0.49, 95퍼센타일 1.93 / 3.06, 최대 32.4 / 50.1), `grade`가 달라진 셀 **3.85 / 4.36%**, `data_status` 100% 동일, `lookup_substituted_rows` 228 → 120 / 0 → 16, `history_window_days` 14 → 7. 지난 GRU 도입(변경 통지 01: 평균 4.7 / 4.4%p)보다 값은 훨씬 덜 움직인다. 통지문 `.claude/handoff/TO_BE-crowd-routing-change-02.md` |
| **이벤트 커버리지 메타(200)** | 배치가 이벤트 표를 `crowd_events_files`(콤마 구분 다중 파일, 뒤 파일이 같은 키를 덮어씀)로 읽어 2026 이후 대상 날짜에도 경기·축제가 붙는다. 표가 그 날짜를 덮는지를 meta로 노출한다 | `/crowd/meta` 필드 2개 추가(`events_coverage_end`·`events_available`, additive) — 배치 `.meta.json` 키도 21→23개(2개 추가). 기존 필드·키는 그대로다 |
| **2024-25 최종 fit 승격(200)** | 라우팅 표는 그대로. LightGBM(`…_masked-stack_train2024-2025`)·GRU(`dl_gru_s14_noev_s42_train2024-2025`) 둘 다 2024+2025 전체로 재적합해 `promote_artifact`로 승격(`MODEL_REGISTRY.md` 4b). 2023은 뺀다(masking-check 13·17절) | 스키마·키 변경 없음. `predictor_version` 두 값이 바뀐다. **값 드리프트**(09-13/14 `d7_only`, 1113 판 → 2024-25 판, 21,606행 행 정렬): `congestion_pct` 평균 \|Δ\| **0.41 / 0.41%p**(중앙값 0.23 / 0.24, 95퍼센타일 1.34 / 1.31, 최대 31.8 / 42.5), `grade` 변화 셀 **3.71 / 3.71%**, `data_status` 100% 동일, `lookup_substituted_rows` 120 → 334 / 16 → 36(2024-25 판이 음수 셀을 더 내고 lookup으로 대체됨 — 인원 하한 규칙은 그대로). 보유 평가 연도가 없어 성능 표는 없다 — 2026 실측 누적 시 사후 검증. 통지문 `.claude/handoff/TO_BE-crowd-artifact-refit-03.md` |

---

## 7. 열차·노드 표 — `predictions_train_{YYYY-MM-DD}.parquet`(239, 옵션)

**분해이지 예측이 아니다** — 슬롯 표(1절)의 30분 보정 혼잡도 총량을 시각표로 나누고 열차 궤적을
역(노드) 관점으로 재색인할 뿐, 새 정보를 만들지 않는다(`RESOLUTION_LADDER.md` §1.1·§3 L4·L5).

경로: `AI/data/CROWD/serving/predictions_train_{YYYY-MM-DD}.parquet`. **`crowd_train_table=true`
(설정값, CLI `--trains`)일 때만 만들어진다** — 기본은 꺼짐이고, 꺼져 있으면 이 파일 자체가 없다.
크기: 열차 한 대 × 역 하나가 한 행이라 **평일 약 10.5만 행/일**(시각표의 열차-역 통과 행 수와
거의 같다 — 슬롯 값이 NaN인 열차 행도 상태를 상속해 남기므로, 값 있는 셀만 셌던 135의 6.7만
행보다 많다).

| 컬럼 | 타입 | 의미 | null 가능 |
| --- | --- | --- | --- |
| `date` | datetime64[us] | 대상 날짜(자정) | 없음 |
| `station_no` | int64 | 역번호 | 없음 |
| `station_name` | str | 역명 | 있음 |
| `line` | str | 호선 | 있음 |
| `direction` | str | `상선`/`하선`/`내선`/`외선` | 없음 |
| `segment` | str | 토폴로지 세그먼트 이름(`line_topology.yaml`, "본선" 등 이름이 호선 간 겹칠 수 있다) | 없음 |
| `to_station_no` | Int64 | 이 열차가 다음에 서는 역(종점이면 없음) | 있음 |
| `prev_station_no` | Int64 | 이 열차가 직전에 선 역(그 런의 첫 정차역이면 없음) | 있음 |
| `train_id` | str | 시각표 열차코드 | 없음 |
| `run_id` | int64 | 같은 `train_id`를 배차 간격(`max_gap_min` 초과)으로 끊은 운행 번호(2호선 순환 등 재사용 대응) | 없음 |
| `pass_time` | str | 이 역을 지나는 계획 시각(`HH:MM[:SS]`, 시각표 `arrival_time`) | 없음 |
| `express` | bool | 급행 여부(시각표) | 있음 |
| `time_slot_30min` | str | 소속 30분 슬롯(`"08:30"`) | 없음 |
| `headway_min` | float64 | 직전 열차와의 배차 간격(분). 그 역·방향·요일유형의 첫차는 슬롯 길이(30)로 대체 | 없음 |
| `headway_long` | bool | 배차 간격이 `long_headway_min`(12분)을 넘는지 — 균등 도착 가정이 약한 열차 표시 | 없음 |
| `mix_w` | float64 | 도착 혼합 가중 `w(headway)`(1=무작위 도착, 0=시각표 의존, 92) | 없음 |
| `share` | float64 | 이 열차가 그 슬롯 재차인원에서 차지하는 몫(2층 배분, 질량 보존) | 없음 |
| `load_arr_est` | float64 | 도착 재차(%, 정원 대비) — 직전 정차역의 `load_dep_est` | **있음** — 슬롯 결측 상속·경로 단절(`arr_source="gap"`) |
| `load_dep_est` | float64 | 출발 재차(%, 정원 대비). 기존 슬롯 표 `congestion_pct`와 같은 정의를 열차 단위로 나눈 값 | **있음** — 슬롯 표 결측 상속 |
| `onboard_arr_est` | float64 | 도착 재차인원(명) | **있음** |
| `onboard_dep_est` | float64 | 출발 재차인원(명) | **있음** |
| `boarding_train_est` | float64 | 이 열차에서 이 역에 타는 인원(명, 1층 30분 비중 × 2층 몫) | **있음** |
| `alighting_train_est` | float64 | 이 열차에서 이 역에 내리는 인원(명) | **있음** |
| `grade_dep` | float64 | `load_dep_est`를 등급 임계값으로 자른 값(슬롯 표 `grade`와 같은 정의) | **있음** |
| `arr_source` | str | 도착 재차의 출처 — `origin`(그 런의 첫 정차역, 0으로 둠) / `prev_stop`(직전 정차역에서 이어붙임 — 급행·정차 행 결측으로 역을 건너뛰어도 **같은 세그먼트 안이면** 이어붙인다) / `gap`(직전 정차역이 다른 세그먼트에 있어 이어붙일 수 없음 → NaN. 2026-09-14 표에서 1행, 09-13 표 0행) | 없음 |
| `link_ambiguous` | bool | 강동처럼 한 역이 여러 세그먼트에 걸쳐 링크가 중복될 때, 실제 경로(다음 역, 없으면 직전 역)로 못 정해 재차 최댓값 규칙으로 대신 골랐는지 | 없음 |
| `data_status` | str | 슬롯 표(2절)와 같은 값을 상속 | 없음 |
| `pred_source` | str | 슬롯 표(`model`/`lookup_negative`)와 같은 값을 상속 | 없음 |
| `train_capacity` | int64 | 편성 정원(명) | 없음 |

**NaN은 슬롯 표를 상속하고, 채우지 않는다.** 배율표 결측·절단 종점처럼 슬롯 혼잡도가 이미 NaN인
셀은 그 슬롯을 지나는 모든 열차의 `load_arr_est`·`load_dep_est`·`onboard_*_est`·`grade_dep`이
그대로 NaN이다(원칙 8) — 열차 단위로 나눈다고 값이 생기지 않는다. 그 30분에 운행하는 열차가
아예 없는 슬롯(시각표 결측·막차 이후)은 배분할 곳이 없어 표에 행 자체가 없다(메타 `train_rows`가
슬롯 표 21,606행보다 적게 늘어난 정도로 간접 확인 가능).

**강동(5호선) 링크 중복**은 5.4절이 말하는 슬롯 표 중복과 같은 원인(본선 종점·하남선 첫 역이 같은
역)이지만 이 표에서는 `to_station_no`/`prev_station_no`로 실제 경로가 남아 있어 행이 중복되지
않는다 — **링크 배정은 열차 궤적(다음 역, 없으면 직전 역)으로 배분 전에 정해지고**, 링크마다
열차 수·질량이 따로 보존된다(135 버그 수정: 예전에는 배분을 먼저 하고 나서 세그먼트 중복을
나중에 해소해 강동에서 링크별 열차 수·재차인원이 뒤섞였다). 다음 역(없으면 직전 역)과 실제로
이어지는 세그먼트를 골라 `segment`를 정하고, 그래도 안 정해지면(둘 다 없는 퇴화 케이스이거나
후보가 여럿 남으면) 세그먼트 등록 순서에서 역이 첫/끝(종점 링크)인 첫 후보를, 없으면 등록 순서상
첫 후보를 고른 뒤 `link_ambiguous=true`로 표시한다(숨기지 않는다, 원칙 8).

**질량 보존**은 슬롯 표와 열차 표 사이에서 **링크 단위로** 검증한다 — 한 (역, 방향, 링크, 슬롯)의
열차별 `onboard_dep_est` 합은 그 링크·슬롯의 재차인원(`congestion_pct/100 × train_capacity ×
그 링크를 실제로 지나는 열차 수`)과 같아야 하고, 그 최대 절대오차가 메타 `train_mass_gap`이다
(부동소수 오차 수준이어야 정상, `RESOLUTION_LADDER.md` §3 L4의 "질량 보존 오차 3.6e-12"와 같은
성격의 수). 링크를 구분하지 않고 역·방향·슬롯만으로 재면 강동처럼 세그먼트가 겹치는 역에서
중복된 인덱스끼리 빼는 꼴이 되어 오차가 실제보다 훨씬 크게(예: 3만대) 부풀려진다.

---

## 문의

수치 원본은 `AI/validation/CROWD/*/RESULTS.md`, 모델 명세는 `AI/app/CROWD/pipeline/MODEL_REGISTRY.md`.
