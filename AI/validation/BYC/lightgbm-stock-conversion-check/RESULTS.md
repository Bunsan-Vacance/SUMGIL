# LightGBM → 재고 표 변환 (B1/B2) 검증 결과

목표: LightGBM(v3)의 `target_net_flow` 예측을 `bike_stock_pred` 표(exp_bikes/p_empty/p_full)로
바꾸는 방법을 검증한다. A1(anchor 전략)=③ 하이브리드, A2(확률 산출)=③ quantile regression으로
채택(2026-09-14 결정) 후 B1(feasibility)·B2(calibration)를 진행했다.

## 실행 조건

- 데이터: `validation/BYC/full-coverage-check/outputs/full-run/` (전체 대여소, slot_5m 버그 수정 후)
- train=2024-01, valid=2024-12, test=2025-07 (1개월씩만, `sample_frac=0.05`) — 소규모 feasibility용
- quantile: 0.1 / 0.5 / 0.9, `LGBMRegressor(objective="quantile", n_estimators=300, learning_rate=0.05, num_leaves=63)`
- 피처: `app/BIKE/pipeline/features.py`의 `MODEL_FEATURE_COLS`(v3와 동일 세트) 그대로 재사용
- 코드: `src/quantile_feasibility.py`(B1), `src/quantile_probability_check.py`(B2 1차),
  `src/quantile_isotonic_calibration.py`(B2 보정)

## B1 — quantile 학습 feasibility

| 항목 | 결과 |
|---|---|
| 학습 가능 여부 | 가능. quantile 3개 각 5.6~6.1초(train 540,419행 기준) |
| quantile crossing(q10>q50, q50>q90) 위반 | 각 0.2%, 0.4% — 무시 가능한 수준 |
| 예측 범위 | q50 [-16.5, 19.8] — 실측 범위([-42, 57], 평균 -0.008) 안에 정상적으로 위치 |

**전체 스케일(11개월, 45% 샘플, 1500라운드) 추정 시간**: v3 단일 모델이 ~460초였으므로,
quantile 3개면 대략 20~25분으로 추정(실측 아님, 참고용).

## B2 — 확률 변환 calibration

### 1차 (정규분포 근사만, 보정 없음)

quantile 3개(q10/q50/q90)로 `mu=q50`, `sigma=(q90-q10)/(2*1.2816)`인 정규분포를 가정해
`p_empty = CDF(-anchor)`, `p_full = 1-CDF(rack_count-anchor)`를 계산.

| 항목 | 목표 | 실제 |
|---|---|---|
| quantile coverage (q10) | 10% | **17.3%** |
| quantile coverage (q50) | 50% | 50.1% |
| quantile coverage (q90) | 90% | **84.8%** |

→ **양쪽 꼬리가 실제보다 좁게 잡힘**(정규분포 가정이 재고 변화의 두꺼운 꼬리를 못 잡음).
p_full은 그런대로 맞았으나(Brier 0.045, 평균예측 0.460 vs 실측 0.479), **p_empty는 체계적으로
과소평가**(Brier 0.038, 평균예측 0.033 vs 실측 0.051).

### 2차 (isotonic 사후 보정 추가) — **채택**

valid(2024-12)로 raw p_empty/p_full → 실제 발생 여부의 isotonic 보정기를 fit하고,
**한 번도 안 본 test(2025-07)**에서 평가:

| | 실측 발생률 | 보정 전 예측평균 / Brier | 보정 후 예측평균 / Brier |
|---|---|---|---|
| p_empty | 0.051 | 0.032 / 0.0378 | **0.049 / 0.0351** |
| p_full | 0.509 | 0.492 / 0.0469 | **0.509 / 0.0439** |

보정 전/후 모두 test는 valid와 다른 달이라 **일반화가 실제로 확인됨**(같은 데이터로 fit한
것을 그대로 평가하는 순환 검증이 아님). calibration 표도 구간별로 예측·실측이 촘촘히 일치.

## 결론

- **B1·B2 모두 PASS.** quantile(0.1/0.5/0.9) LightGBM + isotonic 사후 보정 조합으로
  p_empty/p_full을 실용적인 수준까지 계산할 수 있음이 확인됨(단, "anchor를 안다"는
  가정 하에서만 — 이 가정 자체는 A1에서 무너짐).
- A2 최종안은 순수 "③ quantile regression"이 아니라 **"③ quantile + ① 사후 보정"의 하이브리드**로
  확정 — quantile만으로는(정규분포 근사) 특히 p_empty가 꼬리에서 과소평가됨.
- **A1은 FAIL.** anchor 롤포워드(직전 슬롯 avg + LightGBM 보정)가 avg 단독보다 안 나음 —
  LightGBM이 다루는 보정 폭이 avg 자체의 오차보다 훨씬 작아서 구조적으로 못 고침.
- **재학습 주기(rolling window) 가설도 기각.** "최신 데이터가 곧 정확도"라는 가정과 반대로,
  기간을 줄이면(최근 3개월/같은 달 1개월) 오히려 더 나빠짐 — 표본 수(노이즈 감소)가
  최신성보다 중요했다.
- **종합 결론**: 지금까지 시도한 방법(quantile+보정, anchor 롤포워드, 기간 단축)으로는
  avg baseline을 못 이겼다. **B4(LightGBM→정적표 전환)는 이 세 가지 접근으로는 실패** —
  avg를 계속 서빙 소스로 유지하는 게 맞고, 다음 시도할 여지가 있다면 "기간을 줄이지 않고
  늘려가는 확장형 재학습"뿐인데 이것도 아직 미검증.

## A1 — anchor 롤포워드 프로토타입 (5개 역 소표본)

anchor = 직전 슬롯의 avg(train) 값, horizon_min=30으로 LightGBM(v3) 호출 → net_flow 보정.

| | avg(train) MAE | LightGBM 보정 MAE |
|---|---|---|
| 5개 역 평균 | 10.735 | 10.992(오히려 소폭 나쁨) |

**LightGBM 보정은 도움이 안 됨.** 원인 분석 중, avg(2024-01~11) 자체가 2025-07 실측과
이미 10~26대 차이난다는 걸 발견 — LightGBM이 다루는 보정 폭(net_flow, 단위 수준)이
이 격차(10~26 단위)보다 훨씬 작아서 구조적으로 못 고침.

## 재학습 주기(rolling window) 가설 검증 — **가설 기각**

"avg가 8개월 전 데이터라 오래돼서 틀렸다 → 최근 데이터로 재학습하면 나아진다"는 가설을
전체 역(30만 행 규모)으로 검증했다. 같은 ground truth(2025-07 실측)에 대해:

| 후보 | 기간 | MAE | 행별 (a)보다 나은 비율 |
|---|---|---|---|
| (a) 2024-01~11 전체(지금 서빙 중) | 11개월 | **5.176**(최선) | — |
| (b) 2024-07만("같은 달, 작년") | 1개월 | 5.923 | 43.5% |
| (c) 2024-09~11만("최근 3개월") | 3개월 | 6.028 | 38.9% |

**결과: "최근 데이터만"도 "같은 달(계절) 맞춤"도 둘 다 "11개월 전체 평균"보다 못하다.**
표본을 많이 모아 평균 내는 것(노이즈 감소)이 최신성·계절 일치보다 더 큰 영향을 준 것으로
보인다. **"최근 N개월 rolling 재학습" 가설은 기각** — 오히려 기간을 줄이지 않고 계속
늘려가는(확장형 window) 쪽이 나을 가능성을 시사(추가 검증 필요, 미확인).

## 실시간 anchor 트랙 (별도, 2026-09-14 논의)

A1의 실패 원인이 "anchor(avg 8개월 전 평균)가 이미 틀려서"였다면, **진짜 실시간 anchor**를 쓰면
LightGBM(v3)이 이미 검증된 성능(MAE 1.6대, `target_net_flow` 기준)을 낼 수 있다는 가설이
있다 — `DATA_ENGINE/collect/bike_realtime.py`가 5분마다 `data/BIKE/raw/realtime/latest.parquet`을
갱신하므로 AI가 BE 없이도 신선한 현재 재고를 직접 읽을 수 있음(BE Redis는 VPN 미구성으로
아직 접근 불가, `-131` 문서 참고).

**중요한 caveat**: 학습에 쓴 `stock_anchor_hour`는 `station_stock_hourly`(1시간 단위) 기반이고,
`minutes_since_stock_anchor`도 "1시간 읽기 후 경과 시간" 분포로 학습됐다. `latest.parquet`은
5분 단위로 훨씬 신선해서, 모델이 학습 때 본 적 없는 입력 분포(항상 매우 작은
minutes_since_anchor)를 받게 된다. **MAE 1.6대가 이 조건에서도 재현되는지는 별도 소규모
검증이 반드시 필요하다 — 단정 금지.**

**실행 전 확인 필요(2026-09-14 기준 블로킹)**: 로컬 저장소엔 `data/BIKE/raw/realtime/`에
`.gitkeep`뿐, 실제 수집 스냅샷이 없다. 수집기 배포가 9월 12일이라 서버에 쌓인 이력이
길어야 이틀 — 요일유형 3종을 다 커버 못 할 가능성이 높다. **서버/Drive 백업의 실제 누적량
확인 후 진행.** 데이터 부족하면 정적 표 고도화(주변 대여소 피처)를 먼저 진행.

## 0단계 — 데이터 가용성 확인 (2026-09-14)

| 소스 | 상태 |
|---|---|
| 날씨(실측, ASOS 지점108) | ✅ 2024·2025 둘 다 있음(`data/EXTERNAL/weather/raw/asos/`) |
| 날씨(예보/nowcast) | ❌ 이력 없음(수집기 배포 9/12, 하루치뿐) — 예보 기준 검증은 보류 |
| KBO | ✅ `kbo_games_with_attendance.parquet`, 2024-03-23~2025-10-03 커버(재사용, 새로 안 만듦) |
| 유동인구 raw | ❌ 2026년 3~8월분뿐 — 우리 학습(2024)/테스트(2025) 기간과 안 맞음, 제외 확정 |
| 공휴일 | ✅ 기존 `holiday_calendar.parquet` |

## 0-2 효과 사전 검증 — **1차(net_flow 평균만) 판단이 틀렸음, 3지표로 재검증**

**교훈**: net_flow(순증감) 평균은 대여·반납이 같이 늘거나 줄면 서로 상쇄돼 신호가 안 보인다.
활동량(대여+반납)과 미래 empty/full 발생률(`stock_anchor_hour + target_net_flow`로 계산)까지
같이 봐야 한다.

### 날씨 (`weather_effect_check.py`, `effect_recheck_full.py`, 전체 59.4M행)

| | net_flow | 활동량 | empty_rate | full_rate |
|---|---|---|---|---|
| 비 안 옴 | -0.0028 | 1.547 | 0.048 | 0.480 |
| 비 옴 | -0.0384 | 1.326(**-14.3%**) | 0.036(**-0.012**) | 0.510(**+0.030**) |

기온: 영하권 활동량 1.30 vs 20~30도 1.60(**+23%**). → **날씨 채택**.

### KBO (`kbo_effect_check.py`, 잠실 27역·고척 37역, 1.66M행)

| 구장 | 활동량 변화 | empty_rate 변화 | full_rate 변화 |
|---|---|---|---|
| **잠실** | **+11.2%** | **+0.024**(0.033→0.058) | **-0.10**(0.443→0.343) |
| 고척 | +4.0% | -0.004 | +0.052 |

잠실은 net_flow 평균으로도(-0.0079), 시간대별로 쪼개도(경기 시간대 -0.04~-0.10) 안 보이던
신호가 활동량·empty/full 기준으로는 뚜렷했다. → **KBO(잠실) 채택, 고척은 약해서 보류**.

### 공휴일 (`effect_recheck_full.py`, 전체 59.4M행)

| | 활동량 | empty_rate | full_rate |
|---|---|---|---|
| 평일 | 1.559 | 0.050 | 0.478 |
| 공휴일 | 1.493(**-4.2%**) | 0.043(**-0.007**) | 0.488(**+0.010**) |

날씨·KBO보다는 약하지만 무시할 수준은 아님. → **공휴일 세분화 채택**.

### 유동인구

데이터 시기(2026년) 불일치로 재평가 불가 — **제외 확정 유지**.

## 결론 — 0단계 뒤집힘

1차 판단(전부 net_flow만 봐서 기각)은 틀렸다. **날씨·공휴일·KBO(잠실) 셋 다 채택**,
날짜축 기반 멀티소스 모델을 진행할 근거가 충분하다고 결론. 1단계(BE 스키마 협의)로 진행.

## 4~5단계 — 날짜축 멀티소스 학습 (`train_multisource_lightgbm.py`)

anchor 없이 target_datetime 맥락(시간·요일·날씨·공휴일·KBO)만으로 절대 재고(`target_stock`)를
직접 예측하는 모델. 전체 스케일(train 11개월 43.5M행, valid 12월, test 2025 Q3 13.0M행),
`n_estimators=1500, learning_rate=0.02, num_leaves=127, early_stopping=60`.

### 1차 시도 — avg 못 이김 (여러 원인 수정 과정)

| 시도 | MAE | 비고 |
|---|---|---|
| baseline1(avg, dow_type×time_slot) | 8.160 | |
| baseline2(month×dow_type×time_slot) | 8.593 | avg보다도 못함(세분화=노이즈↑, 재학습 rolling 기각과 같은 패턴) |
| LightGBM v1(기본 하이퍼파라미터) | 8.359 | avg 못 이김 |
| LightGBM v2(튜닝, historical profile을 target_dow×hour로 계산) | 8.328 | 여전히 못 이김 |
| LightGBM v3(historical profile을 avg와 동일하게 dow_type×time_slot로 수정 + station_code를 카테고리형으로 명시) | 8.207 | 거의 붙었지만 못 이김 |
| LightGBM v4(잔차 학습: target_stock−hist_mean만 예측) | 8.216 | v3와 수학적으로 동치, 개선 없음(예상대로) |

**원인 진단**: (1) 모델에 준 historical profile 피처가 avg보다 노이즈 많은 그룹핑(요일 안 묶음)이었음 →
avg와 동일 그룹핑으로 수정. (2) `station_code`를 정수로 줘서 LightGBM이 순서 있는 숫자로 오인 →
`categorical_feature`로 명시. 둘 다 고쳤지만 **avg를 못 넘었다.**

### CROWD 벤치마킹 후 재시도 — D-1/D-7 lag 추가로 avg 격파

CROWD의 배포 모델(`festival_selflag_d1sd_d7_resid`, `MODEL_REGISTRY.md`)을 보니 날씨·이벤트만으론
+1.5%뿐이고 **자기 역 전날 실측 잔차**를 추가하니 +21.7%로 급상승했다는 게 확인됨 — BIKE에도
동일하게 D-1(어제 같은 시각)·D-7(1주 전 같은 시각) 실측 lag를 피처로 추가.

**중요한 버그 발견 및 수정**: 분(minute) 단위로 정확히 매칭하면 가용률이 27~35%뿐이었음 — 원본이
5분 고정 그리드가 아니라 실제 대여·반납 이벤트만 기록된 데이터라(역당 하루 288슬롯 중 실제로는
50~60개뿐), 분까지 맞추면 거의 안 맞았음. **30분 단위(time_slot)로 집계해서 매칭**하도록 수정 →
가용률 68~78%로 개선.

| | MAE |
|---|---|
| baseline1(avg) | 8.160 |
| baseline2(월별) | 8.593 |
| **LightGBM(D-1/D-7 lag 포함, 전체 스케일)** | **7.217** (avg 대비 **-11.6%**) |

Dec 검증 l2도 111.4로, lag 없을 때(159) 대비 크게 낮아짐. **B4 최초로 avg를 명확히 이김.**

## p_empty/p_full — D-1/D-7 lag 포함 quantile+isotonic 재확인 (`train_multisource_quantile.py`)

exp_bikes와 같은 피처(날씨·공휴일·KBO·D-1/D-7 lag)로 quantile(0.1/0.5/0.9) 3개 학습 +
isotonic 보정. avg 쪽 확률은 `StockProfileBaseline`과 동일한 계산(station×dow_type×time_slot
실측 empty/full 비율). 전체 스케일(train 43.5M행, test 13.0M행), 학습 3299초(55분,
q50 모델은 1500라운드 다 써도 early stopping 안 걸림 — 개선 여지 있으나 시간 대비 판단 보류).

| | avg | model(보정 전) | model(isotonic 후) | 개선율 |
|---|---|---|---|---|
| **p_empty** | 0.0656 | 0.0655 | 0.0644 | **-1.8%**(근소— avg의 절대 수준 자체가 이미 낮아 개선 여지 적음) |
| **p_full** | 0.1849 | 0.1633 | 0.1619 | **-12.4%**(확실) |

## 결론 (최종)

날짜축 멀티소스 모델은 **D-1/D-7 lag 피처가 핵심**이었다 — 날씨·공휴일·KBO는 0단계에서 신호가
있다고 확인됐지만, 그것만으론 avg를 못 이겼고 어제/1주 전 실측 lag를 더해야 이겼다(CROWD와
같은 패턴).

**세 지표 종합**: exp_bikes -11.6%, p_full -12.4%(둘 다 확실한 개선), p_empty -1.8%(약하지만
avg를 넘김 — avg 자체 수준이 이미 낮아 더 줄일 여지가 작다고 판단, 추가 투자 보류).

**결정 게이트 통과 → predictor.py 구현 재개(Phase A).** p_empty는 "약하게 이김"으로 기록하고
향후 개선 후보(직접 분류기 등)로 남긴다.

## 다음 검토 여지 (미해결)

- 지금은 소규모(1개월, 5% 샘플)만 확인함 — 전체 스케일에서도 같은 calibration이 유지되는지는
  A1까지 끝난 후 종합 비교(Phase B3 격)에서 재확인 필요.
- isotonic 보정기 자체도 station·시간대별로 편차가 있을 수 있음(전체 통합 하나로 fit함) —
  전체 스케일 검증 때 station별/시간대별로 쪼개는 게 나은지도 같이 볼 것.
