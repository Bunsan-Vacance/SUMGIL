# 전체 대여소 커버리지 — avg baseline vs LightGBM 검증 결과

작성: 2026-09-13. `build_full_station_netflow.py`로 만든 전체 대여소(~2,556개) 데이터셋
(train 2024-01~11, valid 2024-12, test 2025 Q3, 250.7M행)을 대상으로 avg(Naive_Profile)와
LightGBM을 비교한다.

## 실행 조건

- 데이터: `AI/validation/BYC/full-coverage-check/outputs/full-run/*.parquet`
- train: 2024-01~2024-11 (11개월), valid: 2024-12, test: 2025-07~09 (3개월)
- station: 매핑된 전체(train 2,556개, test 2,590개 — 연도별 station info 스냅샷 차이)
- LightGBM은 메모리 제약(전체 태우면 역산 ~47GB > RAM 31.5GB)으로 **train만 파일별 45% 샘플링**
  (`--sample-frac 0.45`, 84.1M행). avg baseline은 스트리밍 부분합이라 샘플링 불필요, 전체 사용.
- 환경: RAM 31.5GB, 실행 스크립트는 매 단계 `PeakMemoryTracker`로 피크 RSS 기록.

## 핵심 결론

**MAE·RMSE·R²는 LightGBM이 이기고, direction_accuracy는 사실상 동률(0.0003p 차이)이다.**
Phase 0~3(top300/stratified300, 300개 표본)에서는 tree 모델이 MAE/R²는 이겨도
direction_accuracy는 항상 지는(격차 0.02~0.17p) 패턴이 반복됐는데, **전체 대여소 스케일 +
historical profile feature 조합에서 처음으로 그 격차가 거의 사라졌다.**

## 시행착오 — v1(최소 feature) → v2(historical profile 추가)

| | train 스코프 | MAE | RMSE | R² | dir_acc |
|---|---|---|---|---|---|
| v1 (Phase 1 최소 feature셋) | 11개월, 45% 샘플 | 1.75(가중) | 2.41 | 0.125 | 0.479 |
| v2 (Phase 2 historical profile 추가) | 11개월, 45% 샘플 | **1.6868** | **2.2793** | **0.2149** | **0.5012** |
| avg(Naive_Profile) | train 전체(비샘플) | 1.6923 | 2.2884 | 0.2095 | 0.5009 |

v1은 avg baseline보다 **전부** 못했다(top300 Phase 1과 같은 패턴 재현). Phase 2의 historical
profile feature(station×dow×hour×horizon 과거 평균/표준편차, train만으로 fit)를 추가하자
MAE/R²가 뒤집혔고, direction_accuracy 격차도 거의 사라졌다 — Phase 1만 보고 "LightGBM이
전체 스케일에서 진다"고 결론 냈으면 틀렸을 뻔했다.

## 최종 수치 (test, 2025 Q3 3개월 합산 51,891,246행)

| 지표 | avg(Naive_Profile) | LightGBM v2 |
|---|---|---|
| MAE | 1.6923 | 1.6868 |
| RMSE | 2.2884 | 2.2793 |
| R² | 0.2095 | 0.2149 |
| WAPE | (미측정) | 0.9422(가중) |
| direction_accuracy | 0.5009 | 0.5012 |
| direction_macro_f1 | **0.3700** | 0.3646 |

direction_macro_f1은 avg가 근소 우위 — 다수 클래스(stable) 비중이 커서, 전체 accuracy는
비슷해도 소수 클래스(decrease/increase)까지 균등하게 보면 avg가 약간 더 균형 잡힌 것으로
해석된다.

## 메모리·시간 실측 (스케일 결정 과정)

| 조건 | train 행수 | 피크 메모리 | 총 시간 |
|---|---|---|---|
| 2개월, v1 | 21.5M | (미측정) | ~110초 |
| 5개월, v1 | 77.3M | 19.7GB | ~360초 |
| 5개월, v1 샘플 45% | 34.8M | 11.2GB | ~280초 |
| **11개월, v1 샘플 45% (전체)** | 84.1M | **21.2GB** | ~670초 |
| 5개월, v2 (비샘플) | 77.3M | 18.5GB | ~150초 |
| **11개월, v2 샘플 45% (전체)** | 84.1M | **18.9GB** | ~390초 |

11개월 전체를 비샘플로 그대로 태우면 역산 ~47GB로 RAM(31.5GB) 초과 예상 — 45% 샘플링으로
해결. v2는 historical profile feature 덕에 조기종료가 훨씬 빨리 걸려(25~33라운드, v1은
500라운드 다 채움) v1보다 오히려 빠르다.

## 다음 검토 여지 (미해결)

- direction_macro_f1의 근소한 격차(avg 우위)가 실사용에 의미 있는 차이인지 — 클래스별
  precision/recall을 따로 뜯어봐야 한다.
- 45% 샘플링이 최종 모델 품질에 주는 영향 — 전체(비샘플)로 돌릴 방법(월별 warm-start 등)을
  나중에 시도해 비교할 가치 있음(이번엔 시간 제약상 샘플링만 검증).
- num_leaves·learning_rate 등 하이퍼파라미터는 top300 실험 기본값 그대로 — 전체 스케일에
  맞춘 재튜닝은 아직 안 함.

## 산출물 위치

```
outputs/full-run/                        전체 대여소 매핑 데이터셋(월별 parquet, 250.7M행)
outputs/avg-baseline/                    avg baseline profile 3종 + eval_report.csv
outputs/lightgbm-full/eval_report_v2-full.csv   LightGBM v2 최종 평가
models/BIKE/v2-full_<timestamp>/         LightGBM v2 모델 아티팩트 + meta.json
```
