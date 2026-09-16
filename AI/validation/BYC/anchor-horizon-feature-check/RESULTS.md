# anchor+horizon LightGBM 피처 확장 검증 (S15P21A104-160)

## 목적

`app/BIKE/pipeline/train.py`(anchor+horizon, `target_net_flow` 예측)의 기본 피처셋(v3,
22개)에 새 피처를 하나씩 독립적으로 추가해서 avg 소스가 아니라 **v3 자체를 이기는지**
확인한다. 기준은 MAE/RMSE/R²(방향 분류 정확도 아님 — 우리는 증감 회귀값을 그대로 쓴다).
피처는 한 번에 여러 개를 묶지 않는다(묶으면 어느 피처가 원인인지 구분이 안 됨).

## 실행 조건 (모든 세트 공통)

```
train: 202401~202411 (11개월), valid: 202412, test: 202507~202509
sample_frac: 0.45, n_estimators 1500, learning_rate 0.02, num_leaves 127,
early_stopping_rounds 60, random_state 42
```

```bash
cd AI
python -m app.BIKE.pipeline.train --train-months 202401 202402 202403 202404 202405 202406 \
    202407 202408 202409 202410 202411 --valid-months 202412 --test-months 202507 202508 202509 \
    --sample-frac 0.45 --tag <태그> --feature-set <세트>
```

## 결과

| split | 지표 | v3 (기준, 22피처) | v4_kbo_lag (+5, 27피처) | v4_weather (+2, 24피처) |
| --- | --- | --- | --- | --- |
| valid | MAE | 1.4806 | 1.4817 | **1.4797** |
| | RMSE | 1.9787 | 1.9794 | **1.9766** |
| | R² | 0.3304 | 0.3300 | **0.3319** |
| test:202507 | MAE | 1.6090 | 1.6106 | **1.6061** |
| | RMSE | 2.1746 | 2.1772 | **2.1683** |
| | R² | 0.3255 | 0.3239 | **0.3294** |
| test:202508 | MAE | 1.6095 | 1.6108 | **1.6077** |
| | RMSE | 2.1673 | 2.1695 | **2.1629** |
| | R² | 0.2897 | 0.2883 | **0.2926** |
| test:202509 | MAE | 1.6621 | 1.6641 | **1.6580** |
| | RMSE | 2.2887 | 2.2922 | **2.2788** |
| | R² | 0.3186 | 0.3165 | **0.3245** |

**아티팩트**: v3=`models/BIKE/v3-holiday-tuned_20260913-1558`,
v4_kbo_lag=`models/BIKE/v4-kbo-lag_20260916-1651`, v4_weather=`models/BIKE/v4-weather_20260916-1725`.

참고(변화량=0 baseline, test MAE): 202507 1.830 / 202508 1.797 / 202509 1.885 — v3/v4 계열
전부 이 단순 기준선은 확실히 이긴다.

## 판정

- **v4_kbo_lag(KBO+D-1/D-7 lag) — 기각.** v3보다 모든 split·모든 지표에서 일관되게
  근소하게 나쁘다(0.05~0.2% 수준이지만 4개 split × 3개 지표 전부 같은 방향). 원인 추정:
  이 모델은 이미 `stock_anchor_hour`(실시간 재고)가 피처로 있어서, 그 신호가 없던
  날짜축 멀티소스 모델(`lightgbm-stock-conversion-check/RESULTS.md`)과 달리 D-1/D-7
  lag가 추가 정보를 거의 못 준다. KBO와 lag를 같이 묶어 테스트해서 둘 중 무엇이 원인인지는
  분리하지 못했다 — 재검토 시 각각 단독으로 다시 볼 것.
- **v4_weather(날씨: is_rain·temp) — 채택.** v3보다 **모든 split·모든 지표에서 일관되게
  개선**(MAE 0.06~0.25%, R² 0.15~1.3%p 수준 — 작지만 방향이 전부 같다). ASOS 실측이
  학습·평가 기간을 이미 커버해서 오프라인 검증엔 문제없었다.
  **서빙 반영 전 선결 조건**: 지금은 ASOS 과거 실측만 지원한다 — 실시간 서빙에 쓰려면
  `weather.nowcast` Kafka 토픽을 `bike.stock`처럼 최신 스냅샷화하는 별도 인프라
  (Phase 2와 동일 패턴)가 필요하다. 아직 미착수.

## 다음

1. 역 거리 피처(v4_distance) 독립 검증 — 선행 작업으로 station 거리 데이터를 510개
   역에서 전체(2,583개) 역으로 확장 필요(`build_station_distance_features.py`).
2. 효과 있는 피처들(지금은 weather만)을 나중에 조합한 최종 후보 세트 결정.
3. weather 채택이 최종 확정되면 실시간 날씨 스냅샷 인프라 티켓 별도 발행.
