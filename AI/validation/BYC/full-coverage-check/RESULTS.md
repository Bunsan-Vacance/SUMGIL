# 전체 대여소 커버리지 — avg baseline vs LightGBM 검증 결과

작성: 2026-09-13, 2026-09-14 버그 수정 후 갱신. `build_full_station_netflow.py`로 만든
전체 대여소(~2,556개) 데이터셋(train 2024-01~11, valid 2024-12, test 2025 Q3, 250.7M행)을
대상으로 avg(Naive_Profile)와 LightGBM을 비교한다.

## ⚠️ 2026-09-14 버그 수정 — 이전 수치는 무효

**`_read_rental_day()`가 `기준_시간대`(HHMM 형식, 예: "1750"=17:50)를 그냥 5로 나눠서
`slot_5m`을 만들었다.** 이 계산은 시(hour)가 0일 때만 우연히 맞고 그 외엔 다 틀린다
(`1750 // 5 = 350`, 정답은 `(17*60+50)//5 = 214`). 시간대별 대여량을 찍어보고 발견함
(1시=40만·6시=72만·16시=8만 식으로 뒤죽박죽 — 실제로는 새벽 저조·출퇴근 피크의 완만한
곡선이어야 함).

```python
# 틀렸던 코드
df["slot_5m"] = df["기준_시간대"] // SLOT_MINUTES

# 수정
hh = df["기준_시간대"] // 100
mm = df["기준_시간대"] % 100
df["slot_5m"] = hh * 12 + mm // SLOT_MINUTES
```

`hour`/`minute`/`datetime_5m`/`sin_hour`/`cos_hour`/`sin_slot`/`cos_slot`이 전부 잘못된
값이었고, 가장 심각하게는 **`stock_anchor_hour`(재고 anchor)를 `merge_asof`로 조인할 때
엉뚱한 시각의 재고와 매칭**됐다(예: 실제 10시 이벤트가 16시대 재고와 매칭). 이 문서의
Phase 1 수치(v1/v2 첫 비교)는 이 버그가 있는 데이터로 만들어졌던 것 — 전부 재실행했다.
같은 김에 발견한 부수 버그: 일부 파일이 줄 끝 trailing comma로 빈 컬럼이 하나 더
잡혀서 컬럼 수 검증에 걸렸던 것도 같이 고침(마지막 열이 전부 결측이면 버림).

## 실행 조건

- 데이터: `AI/validation/BYC/full-coverage-check/outputs/full-run/*.parquet` (버그 수정 후 재빌드)
- train: 2024-01~2024-11 (11개월), valid: 2024-12, test: 2025-07~09 (3개월)
- station: 매핑된 전체(train 2,556개, test 2,590개 — 연도별 station info 스냅샷 차이)
- LightGBM은 메모리 제약(전체 태우면 역산 ~47GB > RAM 31.5GB)으로 **train만 파일별 45% 샘플링**
  (`--sample-frac 0.45`, 84.1M행). avg baseline은 스트리밍 부분합이라 샘플링 불필요, 전체 사용.
- 환경: RAM 31.5GB, 실행 스크립트는 매 단계 `PeakMemoryTracker`로 피크 RSS 기록.

## 핵심 결론 (버그 수정 후)

**avg(Naive_Profile)와 LightGBM v2가 5개 지표에서 실질적으로 동률이다.** 시간 정보가
정확해지자 avg baseline 자체가 크게 좋아졌다(R² 0.21→0.31 — "이 시간대 평균"이 이제야
진짜 그 시간대를 가리키므로). 버그가 있을 때는 LightGBM이 MAE/RMSE/R²에서 뚜렷하게
앞섰는데, 고치고 나니 그 우위가 거의 사라졌다 — **버그가 avg baseline에 불리하게
작용해 LightGBM의 우위를 과장했던 것.**

| 지표 | avg(Naive_Profile) | LightGBM v2 |
|---|---|---|
| MAE | 1.6348 | **1.6310** |
| RMSE | **2.2211** | 2.2212 |
| R² | **0.3067** | 0.3058 |
| direction_accuracy | 0.5340 | **0.5373** |
| direction_macro_f1 | **0.3936** | 0.3905 |

5개 중 3개는 LightGBM이 근소 우위, 2개는 avg가 근소 우위 — 어느 쪽도 확실한 승자가
아니다. LightGBM은 샘플링·historical profile feature·하이퍼파라미터 관리가 필요한데
성능은 거의 같으므로, 이후 재튜닝(공휴일 feature, 하이퍼파라미터 조정 등)으로 확실한
우위를 만들 수 있는지가 다음 과제다(사용자 결정: LightGBM 유지, 재튜닝 진행).

## 시행착오 — v1(최소 feature) → v2(historical profile 추가) → 버그 수정

| | train 스코프 | MAE | RMSE | R² | dir_acc |
|---|---|---|---|---|---|
| v1 (버그 O, 최소 feature셋) | 11개월, 45% 샘플 | 1.75(가중) | 2.41 | 0.125 | 0.479 |
| v2 (버그 O, historical profile 추가) | 11개월, 45% 샘플 | 1.6868 | 2.2793 | 0.2149 | 0.5012 |
| avg (버그 O) | train 전체 | 1.6923 | 2.2884 | 0.2095 | 0.5009 |
| **v2 (버그 수정 후)** | 11개월, 45% 샘플 | **1.6310** | **2.2212** | **0.3058** | **0.5373** |
| **avg (버그 수정 후)** | train 전체 | **1.6348** | **2.2211** | **0.3067** | **0.5340** |

v1은 버그 여부와 무관하게 avg baseline보다 못했다(top300 Phase 1과 같은 패턴). Phase 2의
historical profile feature를 추가한 v2는 버그가 있을 때도 없을 때도 v1보다는 확실히
낫지만, **avg 대비 우위는 버그를 고치자 거의 사라졌다.**

## 메모리·시간 실측 (스케일 결정 과정, 버그 수정 전 실측이나 스케일 특성은 동일)

| 조건 | train 행수 | 피크 메모리 | 총 시간 |
|---|---|---|---|
| 2개월, v1 | 21.5M | (미측정) | ~110초 |
| 5개월, v1 | 77.3M | 19.7GB | ~360초 |
| 5개월, v1 샘플 45% | 34.8M | 11.2GB | ~280초 |
| 11개월, v1 샘플 45% (전체) | 84.1M | 21.2GB | ~670초 |
| 5개월, v2 (비샘플) | 77.3M | 18.5GB | ~150초 |
| **11개월, v2 샘플 45% (버그 수정 후 최종)** | 84.1M | **19.9GB** | ~390초 |

11개월 전체를 비샘플로 그대로 태우면 역산 ~47GB로 RAM(31.5GB) 초과 예상 — 45% 샘플링으로
해결. v2는 historical profile feature 덕에 조기종료가 훨씬 빨리 걸림(버그 수정 후도
29라운드, v1은 500라운드 다 채움).

## 다음 검토 여지 (미해결)

- **공휴일 feature 미반영** — `data/EXTERNAL/holiday/interim/holiday_calendar.parquet`가
  이 환경에 없어 dow_type/day_type이 공휴일을 못 구분한다(평일에 낀 공휴일이 "평일"로
  집계됨). 한국 공휴일은 고정 목록이라 API 없이 추가 가능 — 다음 재튜닝 1순위.
- 하이퍼파라미터(`num_leaves`·`learning_rate`)가 top300 실험 기본값 그대로다. 조기종료가
  29라운드에서 걸리는 게 `learning_rate=0.05`가 이 스케일엔 너무 높다는 신호일 수 있음 —
  낮추고 더 오래 학습시켜보는 게 다음 재튜닝 2순위.
- direction_macro_f1의 근소한 격차(avg 우위)가 실사용에 의미 있는 차이인지 — 클래스별
  precision/recall을 따로 뜯어봐야 한다.
- 45% 샘플링이 최종 모델 품질에 주는 영향 — 전체(비샘플)로 돌릴 방법(월별 warm-start 등)을
  나중에 시도해 비교할 가치 있음.
- 정류장 정적 feature(Phase 3, 지하철·버스 도보거리 등)는 510개 station만 계산돼 있어
  전체(~2,556개)로 확장 필요 — top300 기준 "소폭 개선"이었던 전례라 기대치는 낮게.

## 산출물 위치

```
outputs/full-run/                              전체 대여소 매핑 데이터셋(월별 parquet, 250.7M행, 버그 수정 후 재빌드)
outputs/avg-baseline/                           avg baseline profile 3종 + eval_report.csv
outputs/lightgbm-full/eval_report_v2-full-fixed.csv   LightGBM v2 최종 평가(버그 수정 후)
models/BIKE/v2-full-fixed_<timestamp>/          LightGBM v2 모델 아티팩트 + meta.json(버그 수정 후)
```
