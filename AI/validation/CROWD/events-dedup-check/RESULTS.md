# 318 — 배포 이벤트 표 갱신 판단: 축제 중복 제거 후 영향 측정 — 판정: **파서 수정·표 재생성, 배포 아티팩트는 재승격하지 않음**

- 티켓: S15P21A104-318 (227 1.2절 결함의 후속). 브랜치 `docs/CROWD-grade-ownership`.
- 실행 환경: 사용자 PC(Windows, SUMGIL conda), 2026-09-23 09:00~09:40 KST. 베이스 커밋 `f7d119a`.
- 스크립트: `table_diff.py`(표 대조·귀속, 이 폴더), 모델 영향은 `masking-check/compare.py`·`window_diff.py` 재사용(227 3절과 같은 방식).
  결과 원본 `data/CROWD/interim/validation/masking_check/w2024c/`(`window_diff_W.md`, `masking_check_W_창간_쌍차이.parquet`), 로그 `compare_w2024c.log`.

## 1. 질문과 판정 기준(사전 고정)

| 질문 | 기준 |
| --- | --- |
| 재생성 표의 +923행(7,958 → 8,881)이 실제 추가인가, 227 중복 결함인가 | 공통 행의 값이 바뀌었는가(중복이면 기존 행의 `festival_count`가 부풀고, 실제 추가면 새 행만 생긴다) |
| 중복 제거가 배포 모델 성능을 바꾸는가 | 227 3절 기준: 표 W 전체 슬라이스 `rel_RMSE_%` ±0.5% 안이면 "결과를 흔들지 않는다" |
| 재적합·재승격이 필요한가 | 성능 이득이 CI로 확인되거나, 학습·서빙 입력 불일치가 **서빙 출력**에 영향을 주면 필요 |

## 2. 표 대조(`table_diff.py`)

### 2.1 배포 표 vs 09-21 재생성 표

| 비교 | 공통 | 한쪽만 | 공통 행 중 `festival_count` 변화 |
| --- | --- | --- | --- |
| 배포(7,958) vs 재생성(8,881) | 7,958 | 재생성에만 923 | **0** |

+923행은 전부 새 (날짜, 역) 행이고 기존 행은 전 컬럼 동일 → **실제 추가**. 출처는 09-16에 갱신된 `KC_488_WNTY_CLTFSTVL_2023.csv`에 실린 **2024년 개최 축제 18건**(965 역·일). 제45회 서울연극제(대학로, 2024-05-01~06-30, 12역 × 61일 = 732)가 대부분이고 나머지는 대학로·관악 소규모 축제다. 경기(`game_count`) 열은 변화 없음.

### 2.2 227 1.2절 중복 결함의 크기 — 추가분보다 크다

이름·기간이 같은 축제가 연도 파일마다 다른 `festival_id`와 **소수점 4~6자리 다른 좌표**로 재등록돼 있어, 좌표를 포함한 옛 `_DEDUPE_KEYS`를 통과했다.

| 항목 | 값 |
| --- | --- |
| 2024-25 창에 걸치는 축제 | 437건, 그중 이름·기간 중복 113행(56그룹) |
| 좌표 차 > 0.001°인 그룹 | 창 안 15/56(최대 위도 차 0.019°), 전 기간 34/189(최대 0.064°) |
| 재생성 표(8,881행, 합 9,885) → 수정 표(7,958행, 합 7,696) | 공통 7,958행 중 **`festival_count` 감소 1,222행** + 중복 좌표에만 붙어 있던 **923행 소멸**, 합 −22% |
| 배포 표(7,958행, 합 8,942) → 수정 표 | 공통 7,035행 중 감소 1,222행, 배포에만 923행·수정에만 923행(2.3) |
| 서빙용 `crowd_station_events_2026_2026.parquet` | 원천이 2025 파일 하나라 **중복 0** |

즉 학습 표는 부풀린 `festival_count`, 2026 서빙 표는 정상 `festival_count`를 본다(학습·서빙 불일치).

### 2.3 수정 후 재생성

`parsers_festival._DEDUPE_KEYS` → `name, start_date, end_date`(좌표는 남길 행을 고르는 타이브레이커: 좌표 있는 행 → 최신 `source_year`).

| 표 | 전 | 후 |
| --- | --- | --- |
| interim `festival_capital.parquet` | 1,161행 | **921행** |
| `crowd_station_events_2024_2025.parquet` | 7,958행, `festival_count` 합 8,942 | **7,958행, 합 7,696**(count=2 행 1,623 → 515) |
| `crowd_station_events_2026_2026.parquet` | 1,186행 | **동일(변화 0)** |

재생성 표는 09-21 재생성 표에서 923행이 빠진 것과 행 수가 같다 — 빠진 923행 중 908행은 "놀러와 대학로 차 없는 거리 축제"(2025-04-26~09-27, 155일)가 2024·2025 파일에 1km 떨어진 좌표로 이중 등록돼 **역 두 세트에 붙어 있던 것**이고, 중복 제거로 최신(2025) 좌표 한 세트만 남았다. 서울연극제 등 2.1의 실제 추가분은 새 표에 들어 있다.

## 3. 모델 영향 — 표 W(`--base w2024 --other w2024c`, 2025 평가 1,992,900행, 날짜 블록 쌍 부트스트랩 1,000회)

`w2024c` = 새 표로 다시 학습한 마스킹 스택 LightGBM(2024 학습, 배포와 같은 구성). `lightgbm` 행은 **아티팩트를 바꾸지 않고 평가 입력 표만 바꾼 것**(= 표만 교체했을 때 옛 모델이 받는 영향).

| 시나리오 | 계열 | 하차 rel RMSE % [CI] | 승차 rel RMSE % [CI] |
| --- | --- | --- | --- |
| `full` | 새 표 재학습 | −0.067 [−0.136, +0.001] | −0.118 [−0.216, −0.025] |
| `full` | 옛 모델 + 새 표 | +0.004 [−0.008, +0.015] | +0.007 [−0.009, +0.020] |
| `d7_only` | 새 표 재학습 | +0.010 [−0.023, +0.044] | +0.044 [−0.019, +0.102] |
| `d1_only` | 새 표 재학습 | −0.015 [−0.041, +0.011] | −0.138 [−0.177, −0.103] |
| `no_lag` | 새 표 재학습 | +0.102 [+0.075, +0.129] | +0.017 [−0.000, +0.034] |

양수 = 새 표가 낫다. 호선·요일유형 슬라이스 104개 중 |rel| > 0.5%는 3개(1호선 승차 `d1_only` −0.64, `full` −0.55, 1호선 하차 `no_lag` +0.50). 옛 모델 + 새 표는 전 슬라이스 ±0.5% 안.

**읽기**: 축제 열은 배포 모델에서 거의 일을 하지 않는다(198·227과 같은 결론). 중복을 없애면 `full`이 −0.07/−0.12%로 **오히려 아주 조금 나빠지고**(승차는 CI 상한 < 0), 결손 시나리오는 ±0.1%다 — 부풀린 count가 우연히 "대학로 상설 행사" 지시자 역할을 했던 정도의 효과다. 어느 쪽이든 227 기준(±0.5%) 안이다.

## 4. 판정

1. **파서 수정은 채택**(데이터 정합성 결함, 코드 커밋). 표 두 개 재생성. 옛 표는 `_PRE318` 접미로 로컬 보존(현재 배포 아티팩트의 학습 입력이라 재현용).
2. **배포 아티팩트는 재승격하지 않는다.** 이유 셋: (a) 성능 이득이 없다 — 재학습분은 `full`에서 CI로 미세 열세, (b) 학습·서빙 불일치는 **서빙 출력에 영향이 없다** — 서빙(2026 날짜)이 읽는 2026 표는 수정 전후 동일하고, 옛 모델이 새 2024-25 표를 읽는 경우도 ±0.02%다, (c) 재승격은 BE 통지·값 드리프트 비용이 따르는데 그에 상응하는 근거가 없다.
3. 다음 재적합(2026 실측 누적 후 사후 검증, `MODEL_REGISTRY.md` 4b)은 자동으로 새 표를 입력으로 받는다 — 그때 이 표의 3절 수치와 대조한다.
4. 09-21 `_REGEN-20260921` 표는 중복을 그대로 담은 판이라 **사용하지 않는다**(로컬 파일만, 삭제 가능).

## 5. 재현

```bash
cd AI
python -m DATA_ENGINE.eda.parsers_festival                          # 1,161 → 921행
python -m DATA_ENGINE.eda.map_events_to_stations                    # crowd_station_events_2024_2025.parquet
python -m DATA_ENGINE.eda.map_events_to_stations --start 2026-01-01 --end 2026-12-31
python validation/CROWD/events-dedup-check/table_diff.py --out data/CROWD/interim/validation/events_dedup_tables.md
python -m app.CROWD.pipeline.train --mask-mode stack --split-date 2025-01-01 --out-root models/CROWD/_experiments/events318 \
  --panel crowd_panel_2024_2025.parquet --events crowd_station_events_2024_2025.parquet --derived-cache crowd_panel_derived_2024_2025c.parquet --name w2024c_masked-stack
python validation/CROWD/masking-check/compare.py --window w2024c --no-gru --lightgbm models/CROWD/festival_selflag_d1sd_d7_resid_20260913-0340 \
  --masked stack=models/CROWD/_experiments/events318/w2024c_masked-stack \
  --panel crowd_panel_2024_2025.parquet --events crowd_station_events_2024_2025.parquet --derived-cache crowd_panel_derived_2024_2025c.parquet
python validation/CROWD/masking-check/window_diff.py --base w2024 --other w2024c --out data/CROWD/interim/validation/masking_check/w2024c/window_diff_W.md
```
학습 44초·비교 45초(GRU 제외). 표 원본 `data/CROWD/interim/validation/masking_check/w2024c/`, 아티팩트 `models/CROWD/_experiments/events318/`.
