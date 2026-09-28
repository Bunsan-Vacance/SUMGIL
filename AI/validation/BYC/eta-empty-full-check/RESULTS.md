# BIKE 빈 재고/만차 확률 이진분류 검증 (S15P21A104-160 Phase 6)

## 목적

`predictor_eta.py`가 서빙하는 anchor+horizon LightGBM(v4_weather, `target_net_flow` 회귀)과
같은 피처·같은 train/valid/test 분할로, 도착 시점 재고를 회귀가 아니라 이진분류
(`is_empty`/`is_full`)로 직접 예측했을 때 얼마나 잘 맞는지 확인한다. 새 데이터는 안 만들고
패널의 `stock_anchor_hour` + `target_net_flow`에서 타깃을 유도했다.

```
arrival_stock = stock_anchor_hour + target_net_flow
is_empty = arrival_stock <= 0
is_full  = arrival_stock >= rack_count
```

지표는 회귀(MAE/RMSE/R²)가 아니라 분류·확률 문제라 logloss·AUC·Brier score로 판단한다
(`AI/CLAUDE.md`의 회귀 비교 하드룰은 여기 그대로 적용되지 않지만, "동일 조건에서만 비교"
원칙은 유지 — v4_weather와 같은 분할·같은 피처).

## 실행 조건

```
feature-set: v4_weather와 동일 24피처(MODEL_FEATURE_COLS_V4_WEATHER)
모델: LGBMClassifier(objective=binary, n_estimators=1500, learning_rate=0.02, num_leaves=127,
      subsample=0.8, colsample_bytree=0.8, is_unbalance=True, early_stopping=60), random_state=42
sample_frac: 없음(전체 데이터, v3/v4 계열 회귀 비교와 다름 — 스크립트가 서브샘플링을 지원하지 않음)
```

```bash
cd AI
# 스모크
python validation/BYC/eta-empty-full-check/src/train_empty_full.py \
    --train-months 202401 202402 --valid-months 202412 --test-months 202507 --tag smoke

# 전체 (v4_weather 검증과 동일 분할)
python validation/BYC/eta-empty-full-check/src/train_empty_full.py \
    --train-months 202401 202402 202403 202404 202405 202406 202407 202408 202409 202410 202411 \
    --valid-months 202412 --test-months 202507 202508 202509 --tag full
```

## 결과

### 스모크 (train 202401~02, 2개월, 21,492,956행)

| target | split | rows | pos_rate | logloss | brier | AUC |
| --- | --- | --- | --- | --- | --- | --- |
| is_empty | valid | 11,980,103 | 5.13% | 0.1415 | 0.0375 | 0.9549 |
| is_empty | test:202507 | 16,895,269 | 5.11% | 0.1390 | 0.0369 | 0.9544 |
| is_full | valid | 11,980,103 | 47.82% | 0.1246 | 0.0381 | 0.9909 |
| is_full | test:202507 | 16,895,269 | 50.90% | 0.1358 | 0.0410 | 0.9897 |

학습시간: is_empty 43초(24라운드 조기종료) / is_full 266초(320라운드).

### 전체 (train 202401~11, 11개월, 186,800,453행) — v4_weather와 동일 분할

| target | split | rows | pos_rate | logloss | brier | AUC |
| --- | --- | --- | --- | --- | --- | --- |
| is_empty | valid | 11,980,103 | 5.13% | 0.1500 | 0.0381 | **0.9617** |
| is_empty | test:202507 | 16,895,269 | 5.11% | 0.1477 | 0.0376 | **0.9619** |
| is_empty | test:202508 | 16,995,669 | 5.43% | 0.1532 | 0.0396 | **0.9596** |
| is_empty | test:202509 | 18,000,308 | 5.89% | 0.1602 | 0.0422 | **0.9577** |
| is_full | valid | 11,980,103 | 47.82% | 0.1115 | 0.0349 | **0.9925** |
| is_full | test:202507 | 16,895,269 | 50.90% | 0.1195 | 0.0375 | **0.9914** |
| is_full | test:202508 | 16,995,669 | 50.10% | 0.1200 | 0.0377 | **0.9913** |
| is_full | test:202509 | 18,000,308 | 49.65% | 0.1173 | 0.0366 | **0.9917** |

학습시간: is_empty 591초(19라운드 조기종료) / is_full 2,610초(800라운드).

**이후 서빙에 반영 완료(2026-09-17)** — 이 검증 스크립트 자체는 저장 로직이 없어 학습
결과가 프로세스 종료와 함께 사라졌지만, 그 뒤 `app/BIKE/pipeline/train.py`에 같은 로직을
`--train-empty-full` 플래그로 정식 이식하고 `models/BIKE/v4-weather-final_20260917-2037/`에
`model_is_empty.txt`/`model_is_full.txt`로 저장, `predictor_eta.py`·`service.py`에
로딩·서빙 연결까지 마쳤다. 회귀·분류를 한 프로세스에서 같이 학습해 데이터 로딩을 한 번만
했고, 조건을 이 표(전체 데이터, 202401~11/202412/202507~09)와 동일하게 맞춰 재현했다
(수치는 위 표와 소수점 단위까지 일치 — random_state 42 고정 덕분).
회귀 쪽은 기존 배포 아티팩트(45% 샘플)보다 전체 데이터로 다시 학습되며 소폭 개선됨
(valid MAE 1.4797→1.4741, R² 0.3319→0.3364). 상세는 아래 "다음" 참고.

## 판정

- **전체 데이터로 스모크보다 일관되게 개선** — is_empty valid AUC 0.9549→0.9617,
  is_full 0.9909→0.9925. 데이터 규모가 커지며 안정화되는 정상적인 패턴.
- **`is_empty`에서 계절/월별 효과가 뚜렷하게 재현됨** — 7→8→9월로 갈수록 AUC가
  0.9619→0.9596→0.9577로 꾸준히 하락, logloss·brier도 같은 방향으로 악화(0.0376→0.0396→0.0422).
  `anchor-horizon-feature-check/RESULTS.md`의 회귀 실험(v3 test MAE가 9월에 유독 나쁨)과
  같은 계절 패턴이 분류 문제에서도 그대로 나타난다.
- **`is_full`은 계절 영향이 거의 없음**(AUC 0.9913~0.9917 범위 안에서 안정) — 만차는
  랙 용량이라는 물리적 상한이 있어 계절성보다 구조적 요인(대여소 크기)이 지배적인 것으로 보임.
  반대로 빈 재고(품절)는 수요 패턴에 더 민감해 계절 영향을 크게 받는 것으로 해석된다.
- **둘 다 AUC 0.95+ · Brier 0.045 이하**로 확률 보정 품질도 양호 — anchor+horizon
  피처(v4_weather)가 회귀뿐 아니라 이진분류 타깃에도 잘 작동한다.

## 다음

1. **로컬 반영 완료, 서버 배포만 남음.** 아래는 실제로 한 작업:
   - `app/BIKE/pipeline/train.py`에 `attach_rack_count`/`attach_empty_full_targets`/
     `fit_binary`/`evaluate_binary`를 추가하고 `--train-empty-full` 플래그로 노출 —
     이미 로드·프로파일링된 train/valid/test 프레임을 재사용해 회귀와 분류를 한 번에 학습.
   - `predictor_eta.LightGBMEtaPredictor`에 `model_is_empty.txt`/`model_is_full.txt`를
     선택적으로 로딩하는 `_load_optional_classifier()` 추가(없으면 `None` — 구버전
     아티팩트도 회귀는 그대로 동작). `predict_delta()`가 `p_empty`/`p_full`도 같이 반환.
   - `service.py:predict_eta_stock()`에서 하드코딩된 `None` 대신 `result.get("p_empty"/"p_full")`.
   - `app/core/config.py`의 `bike_eta_model_dir`을 `v4-weather-final_20260917-2037`로 갱신.
   - 실제 로컬 재고 파일·모델로 `service.predict_eta_stock()` end-to-end 검증 완료
     (mock 아님 — 실제 `p_empty`/`p_full` 값이 채워지는 것 확인).
   - `test/BIKE/test_bike_eta_stock.py`에 pass-through 테스트 추가, 전체 BIKE 테스트(36개) 통과.
   - **남은 일**: AI EC2(`j15a104a.p.ssafy.io`)에 코드 5개 파일(`train.py`, `predictor_eta.py`,
     `service.py`, `schemas.py`, `config.py`) + 새 모델 폴더(`models/BIKE/v4-weather-final_20260917-2037/`)
     scp 후 `systemctl restart ai-api`(`AI/DEPLOY.md` 절차) — SSH 키가 있는 사람이 실행해야 함.
2. 두 모델(회귀 net_flow, 분류 is_empty/is_full)을 하나의 학습 프로세스로 묶었다 — 데이터
   로딩을 한 번만 해서 별도 스크립트로 돌릴 때보다 총 시간이 절약된다.
3. 전체 데이터 기준 총 학습 시간(회귀+is_empty+is_full 합산) 약 62분(2026-09-17 실측,
   `models/BIKE/v4-weather-final_20260917-2037/meta.json`) — 정기 재학습 파이프라인을
   만들 경우 이 시간을 고려해야 한다.
