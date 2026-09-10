# Codex CLI Prompt: 따릉이 5분 재고 예측 모델 비교

## 역할
너는 Python 기반 ML 엔지니어링 작업을 수행하는 Codex CLI 에이전트다.  
목표는 이미 생성된 따릉이 5분 단위 복원 재고 데이터셋을 사용해 여러 baseline 모델을 학습/평가하고, 모델 비교 결과표와 저장된 모델 파일을 만드는 것이다.

## 배경
우리는 사용자가 경로 조회를 요청했을 때, 후보 따릉이 대여소의 현재 재고 API 값을 가져오고, 사용자가 해당 대여소에 도착할 ETA 뒤의 예상 재고를 제공하려고 한다.

최종 서빙 식은 다음이다.

```text
predicted_stock = realtime_current_stock + predicted_delta
```

따라서 모델은 절대 재고를 직접 맞히기보다, 특정 horizon 동안의 재고 변화량인 `target_delta`를 예측한다.

## 현재 데이터셋
이미 만들어진 starter 데이터셋은 2025년 9월, OD 활동량 상위 200개 정류장 기준이다.

데이터셋 위치:

```text
C:/Users/SSAFY/Documents/Codex/2026-09-07/https-docviewer-nanet-go-kr-reader/outputs/stock_dataset_202509
```

사용할 파일:

```text
train_202509_top200.csv.gz
valid_202509_top200.csv.gz
test_202509_top200.csv.gz
sample_training_10000.csv
dataset_build_report.md
build_report.json
```

참고:

```text
station_stock_5m_master_202509_top200.csv.gz
```

## 데이터셋 의미
한 row는 다음을 의미한다.

```text
특정 정류장의 특정 5분 시점에서,
현재 재고와 최근 대여/반납 흐름을 보고,
5/10/15/30분 뒤 재고 변화량을 예측한다.
```

주요 컬럼:

```text
station_id
station_no
base_time
horizon_min
current_stock
capacity_proxy
stock_ratio_proxy
rent_count_5m
return_count_5m
net_delta_5m
rent_recent_15m
return_recent_15m
net_recent_15m
net_recent_30m
net_recent_60m
stock_delta_prev_5m
stock_delta_prev_15m
stock_delta_prev_60m
hour
minute
day_of_week
is_weekend
label_type
target_stock
target_delta
target_label_type
```

주의:

```text
label_type = hourly_observed
  실제 시간별 재고 anchor

label_type = reconstructed
  1시간 재고 anchor와 5분 OD 순증감으로 복원한 weak label
```

## 해야 할 작업

### 1. Python 프로젝트 구성
현재 작업 디렉터리에 아래 구조를 만든다.

```text
model_experiments/
  requirements.txt
  src/
    train_baselines.py
    predict_example.py
  outputs/
    model_comparison.csv
    model_comparison_by_horizon.csv
    feature_importance.csv
    best_model.pkl
    feature_schema.json
    metrics.json
```

`requirements.txt`에는 최소한 다음을 넣는다.

```text
pandas
numpy
scikit-learn
joblib
xgboost
lightgbm
```

단, `xgboost` 또는 `lightgbm` 설치가 실패할 수 있으므로, 스크립트는 해당 라이브러리가 없으면 그 모델만 skip하고 나머지는 계속 실행되게 작성한다.

### 2. 학습할 모델
처음 비교할 모델은 다음이다.

```text
Naive_15m_trend
Naive_60m_trend
RandomForest
XGBoost
LightGBM
```

GRU/LSTM은 이번 작업에서 제외한다.  
이유는 현재 목표가 tabular baseline 비교이고, GRU/LSTM은 master table에서 sequence dataset을 별도로 만들어야 하기 때문이다.

### 3. Feature / Target
target은 `target_delta`를 사용한다.

기본 feature 컬럼:

```python
FEATURE_COLS = [
    "horizon_min",
    "current_stock",
    "capacity_proxy",
    "stock_ratio_proxy",
    "rent_count_5m",
    "return_count_5m",
    "net_delta_5m",
    "rent_recent_15m",
    "return_recent_15m",
    "net_recent_15m",
    "net_recent_30m",
    "net_recent_60m",
    "stock_delta_prev_5m",
    "stock_delta_prev_15m",
    "stock_delta_prev_60m",
    "hour",
    "minute",
    "day_of_week",
    "is_weekend",
]
```

`station_id`는 category encoding해서 `station_code` 컬럼으로 추가한다.  
train/valid/test 전체의 station category를 통일해야 한다.

결측치는 0으로 채운다.

```python
X = df[FEATURE_COLS + ["station_code"]].fillna(0)
y = df["target_delta"]
```

### 4. Naive baseline
Naive 모델은 학습하지 않고 계산식으로 평가한다.

```python
Naive_15m_trend:
pred_delta = net_recent_15m / 15 * horizon_min

Naive_60m_trend:
pred_delta = net_recent_60m / 60 * horizon_min
```

### 5. ML 모델

RandomForest:

```python
RandomForestRegressor(
    n_estimators=150,
    max_depth=18,
    min_samples_leaf=3,
    n_jobs=-1,
    random_state=42,
)
```

XGBoost:

```python
XGBRegressor(
    n_estimators=500,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    objective="reg:squarederror",
    tree_method="hist",
    random_state=42,
    n_jobs=-1,
)
```

LightGBM:

```python
LGBMRegressor(
    n_estimators=500,
    learning_rate=0.05,
    num_leaves=63,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    n_jobs=-1,
)
```

가능하면 validation set으로 early stopping을 적용하되, 라이브러리 버전 호환 문제가 생기면 early stopping 없이 실행한다.

### 6. 평가 지표
각 모델에 대해 test set 기준으로 아래 지표를 계산한다.

기본 회귀 지표:

```text
mae_delta
rmse_delta
r2_delta
mae_stock
rmse_stock
```

stock 계산:

```python
pred_stock = current_stock + pred_delta
true_stock = target_stock
```

부족 위험 지표:

```python
shortage_threshold = 2
pred_shortage = pred_stock <= shortage_threshold
true_shortage = true_stock <= shortage_threshold
```

계산할 지표:

```text
shortage_precision
shortage_recall
shortage_f1
```

시간 지표:

```text
train_time_sec
infer_time_sec
infer_rows_per_sec
```

추가로 horizon별 성능도 따로 계산한다.

```text
5분
10분
15분
30분
```

### 7. 출력 파일
아래 파일을 생성한다.

```text
model_experiments/outputs/model_comparison.csv
model_experiments/outputs/model_comparison_by_horizon.csv
model_experiments/outputs/feature_importance.csv
model_experiments/outputs/metrics.json
model_experiments/outputs/best_model.pkl
model_experiments/outputs/feature_schema.json
```

`best_model.pkl`은 다음 기준으로 고른다.

```text
1. Naive보다 mae_stock이 낮아야 함
2. mae_stock이 가장 낮은 모델 우선
3. mae_stock 차이가 작으면 shortage_recall이 높은 모델
4. 성능 차이가 거의 없으면 추론이 빠르고 운영이 쉬운 모델
```

### 8. predict_example.py
저장된 `best_model.pkl`과 `feature_schema.json`을 로드해서 단일 row 예측을 수행하는 예제 파일을 만든다.

입력 예:

```python
sample = {
    "station_id": "ST-102",
    "horizon_min": 10,
    "current_stock": 3,
    "capacity_proxy": 20,
    "stock_ratio_proxy": 0.15,
    "rent_count_5m": 1,
    "return_count_5m": 0,
    "net_delta_5m": -1,
    "rent_recent_15m": 4,
    "return_recent_15m": 1,
    "net_recent_15m": -3,
    "net_recent_30m": -5,
    "net_recent_60m": -7,
    "stock_delta_prev_5m": -1,
    "stock_delta_prev_15m": -3,
    "stock_delta_prev_60m": -7,
    "hour": 18,
    "minute": 30,
    "day_of_week": 1,
    "is_weekend": 0,
}
```

출력:

```text
predicted_delta
predicted_stock
shortage_risk
```

### 9. 성능 이슈 대응
현재 train set은 약 460만 row다. 로컬 머신에서 RandomForest가 너무 느리면 다음 순서로 대응한다.

1. RandomForest는 train sample 1,000,000 row만 사용한다.
2. XGBoost/LightGBM은 전체 train을 사용한다.
3. 그래도 느리면 `--sample-frac 0.3` 옵션을 스크립트에 추가해서 전체 모델을 샘플로 먼저 돌릴 수 있게 한다.

스크립트는 CLI 옵션을 지원한다.

```bash
python model_experiments/src/train_baselines.py \
  --data-dir "C:/Users/SSAFY/Documents/Codex/2026-09-07/https-docviewer-nanet-go-kr-reader/outputs/stock_dataset_202509" \
  --output-dir "model_experiments/outputs" \
  --sample-frac 1.0 \
  --rf-max-rows 1000000
```

### 10. 완료 후 보고
작업 완료 후 다음을 요약해서 알려줘.

```text
1. 어떤 모델을 돌렸는지
2. 어떤 모델이 best_model로 선정됐는지
3. model_comparison.csv 주요 결과
4. horizon별로 성능이 어떻게 달라지는지
5. 다음 단계로 추가할 feature 추천
```

## 중요 제약
- test set으로 튜닝하지 마라.
- train/valid/test는 이미 시간 기준으로 나뉘어 있으므로 섞지 마라.
- `target_delta`를 학습하고, 평가는 `target_delta`와 `target_stock` 둘 다 하라.
- `label_type`과 `target_label_type`은 feature로 쓰지 마라. 데이터 진단용으로만 써라.
- `base_time`은 직접 feature로 쓰지 말고, 이미 생성된 `hour`, `minute`, `day_of_week`, `is_weekend`를 써라.
- 모델 파일만 저장하지 말고 feature column 순서와 station category mapping도 저장하라.
