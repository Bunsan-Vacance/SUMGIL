# CROWD 모델 코드 명세 — 피처 세트 · 아티팩트 · 예측기

혼잡도 예측 모델을 가리키는 코드(이름)가 세 층에 있다. 이 문서는 각 코드가 **무엇을 뜻하고, 어느 티켓에서 나왔고,
수치가 얼마였는지**를 한 곳에 적는다. 수치 원본은 각 `validation/CROWD/*/RESULTS.md`이고, 어긋나면 그쪽이 맞다.

| 층 | 코드 예 | 정의 위치 |
| --- | --- | --- |
| 피처 세트 | `festival_selflag_d1sd_d7_resid` | `features.py: FEATURE_SETS` |
| 아티팩트 | `models/CROWD/festival_selflag_d1sd_d7_resid_20260913-0340/` | `train.py`가 저장, `meta.json` 동봉 |
| 예측기 | `lookup` / `lightgbm:<폴더명>` / `dl:<폴더명>` / `llm` | `predictor.py: build_predictor`, 배치 meta `predictor_version` |

## 1. 모델 구조(모든 세트 공통)

```
예측 = lookup(요일유형 × 역 × 시간대 평균, 2024 학습 구간)  +  LightGBM 잔차(승차·하차 각 1모델)
```

- 타깃은 **1시간 승하차 인원**(패널 273역 × 20슬롯). 30분 혼잡도·열차 단위는 88·92의 변환 층이 뒤에서 만든다 — 모델 코드와 무관.
- 분할은 시간 분할: 2024 학습 / 2025 평가(`dataset.SPLIT_DATE`). 무작위 분할은 같은 날 다른 슬롯이 갈려 누수(87).
- 하이퍼파라미터 `train.DEFAULT_PARAMS`: `n_estimators 300, num_leaves 31, learning_rate 0.05, seed 42`(90 그리드 6조합 차이 0.4%p라 고정).
- 결측은 0으로 채우지 않는다(원칙 8). LightGBM이 NaN을 분할 정보로 받는다 — 단, **학습에서 본 적 없는 결측 패턴은 위험**(4절).

## 2. 피처 세트 코드

이름 규칙: `<외부요인>_<시차 종류>_<시차 간격>_resid`. `resid`는 시차·이웃 값이 원본 인원이 아니라 **lookup 잔차**라는 뜻(89: 원본값 대비 4배 효과).
접두 `festival`은 이벤트 5열(`game_count, festival_count, festival_short_count, festival_long_count, festival_min_duration_days`) + 범주 2열(`station_no, time_slot`)을 포함한다는 표시.

| 코드 | 열 수 | 구성(공통 7열 +) | 예측 시점 전제 | 출처 | 2025 평가, lookup 대비 RMSE 개선율 승/하 (%) | 판정 |
| --- | --- | --- | --- | --- | --- | --- |
| `events_station_time_festival` | 7 | (없음) | 언제나 | 87 | +1.5 / +1.5 | 기준선. 이벤트만으로는 거의 못 맞춘다 |
| `festival_lag_d7_resid` | 13 | 자기 역 1주 전 잔차 2 + 인접역(앞·뒤) 1주 전 잔차 4 | 일별 CSV(주 단위 지연)로 충분 | 89 | +15.2(승) | 원천 지연이 클 때의 **하한** |
| `festival_selflag_d1d7_resid` | 11 | 자기 역 전날 잔차 2 + 1주 전 잔차 2 | D−1 원천 | 89·90 | +21.7 / +23.8 (MAE +28.4 / +27.3) | **90 배포 세트**(93에서 교체됨). 아티팩트 `..._20260911-1533` 보존 |
| `festival_selflag_sameday_d7_resid` | 11 | 전날 **대신** 같은 요일유형 직전 날 잔차 2 + 1주 전 2 | D−1 원천 | 93 B′ | +19.64 / +22.22 | 기각 — 전날을 버리면 전 구간 악화(−2.4%p) |
| **`festival_selflag_d1sd_d7_resid`** | 13 | 전날 2 + 같은 요일유형 직전 날 2 + 1주 전 2 | D−1 원천 | 93 B″ | **+23.38 / +25.36** (MAE +29.56 / +28.42)<br>**95% CI [+21.24, +25.36] / [+23.23, +27.43]**(MAE [+27.59, +31.30] / [+26.66, +29.96], 142) | **현재 배포 세트**(`train.py` 기본값). 휴일 +3.6%p, 어느 호선·요일유형도 악화 없음 |
| `festival_all_derived_resid` | 31 | 위 d1d7 + 같은 시각 인접역·환승 노드 잔차 + 직전 슬롯 잔차 + 인접역 시차 | **실시간 집계**(같은 시각 실측) 필요 | 89·90 | +45.5 / +47.8 | 실시간 원천이 생길 때의 **상한**. D−1 서빙에서 실시간 열을 NaN으로 두고 쓰는 "모델 하나" 안은 +4~8%로 기각(90 마스킹) |

**구간은 날짜 블록 부트스트랩 1,000회다**(142, `validation/CROWD/significance-check/RESULTS.md`). 이 표의 다른 행은 점추정뿐이니
세트끼리 1~4%p 차이로 순위를 매길 때 주의할 것 — 배포 세트의 CI 폭이 4%p라 **d1sd vs d1d7의 +1.37%p,
93이 근거로 든 휴일 +3.6%p는 그 폭 안**이다(같은 행에서의 쌍 비교라 방향은 신뢰할 만하지만 크기는 인용하지 않는다).

### 딥러닝 계열(144·198, `model_kind="dl"`)

피처 세트 코드 체계와 **별개 축**이다 — 세트가 "어떤 열을 쓰나"라면 DL은 "입력을 아예 시퀀스로 받는다"다.
198에서 입력 구성이 `meta.json`의 `seq_features`(시퀀스 채널)·`use_static_events`(정적 이벤트)로 갈린다.

| 코드 | 입력 | 예측 시점 전제 | 출처 | 2025 평가, lookup 대비 RMSE 개선율 승/하 (%) | 판정 |
| --- | --- | --- | --- | --- | --- |
| `dl_gru_s14`(V0, 144 구성) | (역, 대상일) 표본, 직전 14일 × 20슬롯 × **7채널**(z-잔차 2 + 마스크 1 + 요일유형 4) + 정적 **9**(요일 4 + 이벤트 5) + 역 임베딩 | D−1 원천, **이력 0~14일 어디든** | 144 | `full` +8.29 ± 7.04 / +16.43 ± 2.58 (시드 3회)<br>`no_lag` −8.13 ± 6.27 / −2.60 ± 2.12 | 198에서 **교체됨**. 시드 분산이 크다(±7%p) — 시드 1개 비교는 못 쓴다 |
| **`dl_gru_s14_noev`(V3, 채택)** | 위와 같되 **정적 이벤트 5열 없음**(정적 4) | 위와 같음 | 198 | **`full` +20.17 ± 0.32 / +22.60 ± 0.66**<br>`no_lag` **+1.05 ± 1.03 / +1.92 ± 1.36** (MAE full +29.66 / +29.09) | **현재 DL 기본 구성**(`train_dl` 기본값). LightGBM `full`과 3%p 차, `no_lag`에서 **DL 최초로 lookup을 넘는다** |
| `dl_gru_s14_neighbor` (V1) | V0 + 이웃 잔차 z 6 + 이웃 마스크 3 = **16채널** | 위와 같음 | 198 | `full` +10.49 / +18.77, `no_lag` −6.35 / −1.09 | V0보다는 낫고 2호선 열세를 없애지만(−6.16 → +0.85) V3에 못 미친다 |
| `dl_gru_s14_neighbor_noev` | V1 + 정적 이벤트 제거(16채널 + 정적 4) | 위와 같음 | 198 1회 | `full` +19.79 / +23.10, `no_lag` +2.48 / +3.46 | **이웃 효과는 V3와 겹친다** — V3 단독과 차이가 없어 채택하지 않는다(서빙에 이웃 표가 필요해 더 비싸다) |
| `dl_gru_s14_events_hist` (V2) | V0 + 이력 각 날 이벤트 5 = 12채널 | 위와 같음 | 198 | `full` **−76.02 / −7.52** | 기각. 검증(2024-11~12)은 V0과 비슷한데 2025가 무너진다 — 이벤트 채널이 2024 분포에 과적합 |
| `dl_gru_s14_hd3` | V0 구조, Huber δ=3(z 단위) | 위와 같음 | 198 1회 | `full` +4.56 / +15.12 (MAE +22.89 / +22.96) | 기각. 승차·MAE가 δ=1보다 나쁘다 — RMSE 격차는 δ가 원인이 아니다 |
| `dl_gru_s14_notrunc` | V0 구성, 이력 절단 증강 없음 | D−1 원천, 이력 완비 | 144 대조 | `full` +10.38 / +6.70, `no_lag` −34.89 / −48.73 | 대조군. 증강이 결손 내성의 원인임을 보인다 |
| `dl_lstm_s14` | 셀만 LSTM(`--model lstm`), 나머지 V0과 동일 | 위와 같음 | 144 실험 1회 | `full` +7.31 / +7.12, `no_lag` −9.43 / −11.09 | GRU와 구분되지 않아(검증 손실 0.13% 차) **계열 이름은 `gru`로 확정**. 기록용 1행 |
| `dl_lstm_s14_noev` | V3 구성(7채널 + 정적 4)에 셀만 LSTM | 위와 같음 | 198 후속 3시드 | `full` +20.28 ± 0.09 / +24.47 ± 0.63<br>`no_lag` +1.56 ± 0.46 / +2.18 ± 0.62 | **계열 `gru` 유지.** 승차 평균 차 0.11%p가 두 표준편차 합(0.41) 안이라 구분 불가. 하차는 +1.87%p 앞서지만 교체 문턱(+2%p) 미달 — 145 메모 |
| `dl_gru_s14_evfix` | V0 구성인데 이벤트 5열을 **`log1p(x)/log1p(학습 최대)`**로 인코딩(`--event-encoding log1p_max`) | 위와 같음 | 198 후속 3시드 | `full` +19.58 ± 0.71 / +22.27 ± 0.90<br>`no_lag` +1.15 ± 0.61 / +2.70 ± 0.57 | 기각(V3에 −0.59 / −0.33%p). **다만 V0의 붕괴·시드 불안정은 인코딩 탓임을 보인다**(+8.29 ± 7.04 → +19.58 ± 0.71) |

**이벤트 5열은 DL 잔차 예측에 정보를 더하지 않는다(198 판정 1·4 + 후속 B).** 대상일 이벤트를 빼면
`full`·`no_lag`이 **동시에** 오른다(`full` 승차 시드 평균 +8.29 → +20.17). 원인은 값이 아니라 **인코딩**이다 —
99%가 0인 희소 카운트를 z-점수로 넣어 학습 std가 0.07~0.13이고 2025 입력이 최대 87.96까지 튄다.
`log1p_max`로 0~1에 넣으면(`dl_gru_s14_evfix`) 붕괴와 시드 불안정이 사라지지만(+19.58 ± 0.71) **V3를 넘지는
못한다** → 기본값은 이벤트 제거(V3) 그대로다. 같은 방향으로 이력 이벤트를 더 넣은 V2는 −76%로 무너진다.
LightGBM 쪽 이벤트 5열은 재점검하지 않았다 — 트리는 값 분포 이동에 덜 민감하고 z-정규화도 쓰지 않으며
87 이후 세트 비교에서 살아남았으므로 별개 항목이다.

등급 일치율(50/100, 30분 셀 7,158,957개, `full`): lookup 95.37 · lightgbm 96.62(144) · V0 96.695 ·
**V3 96.854** · V1+V3 96.831 · LSTM V3 96.861(보통이상 재현율 90.314로 V3 89.641보다 높다). 하루치(5,460행) CPU 추론 V3 0.35초. 수치 원본
`validation/CROWD/dl-input-check/RESULTS.md`(198)와 `dl-resid-check/RESULTS.md`(144).

같은 요일유형 직전 날(`lagsd_*`)은 평일이면 전날, 토요일이면 지난 토요일, 일요일·공휴일이면 직전 일요일 또는 공휴일이고 14일을 넘으면 NaN
(`lags.attach_same_day_type_lag`, `DERIVED_VERSION=2`).

93의 분할 실험(호선별 8모델 +0.11, 6호선 분리 +0.21, 군집 4모델 +0.47, 6호선은 단독 fit 시 −2.98)은 세트 코드가 아니라 `--group-col`
옵션이고 모두 기각 → 전역 단일 모델.

## 3. 아티팩트

`python -m app.CROWD.pipeline.train [--feature-set …] [--group-col …] [--params JSON]` → `models/CROWD/<feature_set>_<YYYYMMDD-HHMM>/`

| 파일 | 내용 |
| --- | --- |
| `lookup.parquet` | 학습 구간 요일유형×역×시간대 평균(예측의 기준선 부분) |
| `model_boarding.txt`, `model_alighting.txt` | LightGBM 부스터(텍스트 덤프) |
| `meta.json` | `feature_set, feature_columns, categorical_columns, targets, lookup_keys, group_col, derived_version, train_start/end, split_date, n_train_rows, params, created_at, model_files` |

`models/`는 커밋되지 않는다(재생성 가능, 학습 20초). 폴더는 세트별·시각별로 갈리므로 **옛 아티팩트는 지워지지 않고 남는다.**
배치의 `--predictor auto`는 `latest_artifact(kind="lightgbm")`(그 계열 중 폴더명 정렬 최신)을 잡는다 — 특정 아티팩트를
고정하려면 `CROWD_MODELS_DIR`로 폴더를 좁히거나 옛 폴더를 옮긴다. 계열 필터는 4절 `model_kind` 규칙 참고.

현재 로컬 아티팩트(2026-09-14):

| 폴더 | 세트 | 상태 |
| --- | --- | --- |
| `festival_all_derived_resid_20260911-1518` | 실시간 상한 세트 | 90 비교용 보존 |
| `festival_selflag_d1d7_resid_20260911-1533` | 90 배포 세트 | 93까지 배치가 쓴 모델. 보존 |
| **`festival_selflag_d1sd_d7_resid_20260913-0340`** | **현재 배포 세트** | 147에서 학습. `batch_predict --today` meta `predictor_version`으로 확인 |
| `dl_gru_s14_20260914-0949` | 144 GRU = 198 V0(시드 42) | `model_kind="dl"` — `auto`가 고르지 않는다 |
| `dl_gru_s14_s43_…`, `dl_gru_s14_s44_…` | V0 시드 43·44 | 198 시드 분산 측정 |
| **`dl_gru_s14_noev_s42_20260914-1358`** | **198 채택 구성(V3)** | 시드 43·44도 같이 있다(`_noev_s43`, `_noev_s44`) |
| `dl_gru_s14_neighbor_s42_…`, `dl_gru_s14_neighbor_noev_s42_…` | 198 V1 · V1+V3 | 비교 보존 |
| `dl_gru_s14_events_hist_s42_…`, `dl_gru_s14_hd3_s42_…` | 198 V2 · δ=3 | 기각 기록 보존 |
| `dl_lstm_s14_20260914-1236` | 144 LSTM 1회 실험 | 계열 확정 근거. 보존 |
| `dl_lstm_s14_noev_s42_20260914-1457` 외 s43·s44 | 198 후속 — LSTM × V3 3시드 | 계열 재확인(구분 불가). 보존 |
| `dl_gru_s14_evfix_s42_20260914-1501` 외 s43·s44 | 198 후속 — 이벤트 `log1p_max` 인코딩 3시드 | 인코딩 진단 기록. 보존 |
| `dl_gru_s14_notrunc_20260914-0950` | 144 대조군 | 증강 없음. 비교 보존 |

**`--predictor dl`의 아티팩트 선택은 여전히 이름 운이다(144 미해결 8, 198에서 악화).** `latest_artifact(kind="dl")`는
폴더명 정렬 최신을 고르는데 이제 `dl_lstm_s14_…`가 맨 뒤라 **LSTM 대조군**이 잡힌다. `auto`는 lightgbm만 보므로
운영에는 영향이 없지만, DL을 실제로 쓰게 되면(145·197) `--artifact-dir`로 못박거나 선택 규칙을 손봐야 한다.

DL 아티팩트는 폴더 구성이 다르다: `model.pt`(state_dict) · `scale.parquet`(역×슬롯 잔차 표준편차) ·
`lookup.parquet` · `event_stats.parquet` · `meta.json` · `history.json`(에폭별 train/valid 손실).
`meta.json`에는 `model_kind, model, seq_days, hidden, channels, seq_features, use_static_events, event_encoding,
stat_features, huber_delta, station_ids, derived_version, splits, seed, epochs_run, best_epoch, train_seconds,
device, truncation, p_full, determinism`이 들어간다. `event_stats.parquet`에는 두 인코딩의 상수(`mean`·`std`와
`log1p_max`)와 실제로 쓴 `encoding`이 같이 들어 있다. `seq_features`·`use_static_events`·`event_encoding`이 없는
144 아티팩트는 `DLPredictor`가 `base` + 정적 이벤트 있음 + `zscore`로 읽는다(하위 호환) —
`device`·`train_seconds`·`determinism`(같은 시드 2회 학습의 검증 손실 차이)은 149 GPU 규약의 기록 항목이다.

## 4. 예측기 코드와 운영 규칙

| kind | 뜻 | 언제 쓰이나 |
| --- | --- | --- |
| `lookup` | 평균만. 네이버·카카오 수준의 정직한 기준선 | 아티팩트가 없을 때의 `auto`, 그리고 `--predictor lookup` 명시(197부터 "이력 전무 시 자동 대체"는 없어지고 라우팅이 `dl`을 쓴다) |
| `lightgbm:<폴더>` | lookup + 잔차 모델 | `auto` 기본, 그리고 라우팅의 `full`(197) |
| `dl:<폴더>` | lookup + GRU 시퀀스 잔차(144·198) | 명시 지정(`--predictor dl`), 그리고 라우팅의 `d1_only`·`d7_only`·`no_lag`(197). `auto`는 여전히 고르지 않는다 — `crowd_dl_artifact`로 폴더명을 고정한다(아래 "DL 배포판") |
| `llm` | 시차·이벤트를 프롬프트로 주고 수치를 받는 실험 축 | 145 비교 실험 전용. 프로덕션 기본값 아님 |

**`model_kind` 규칙(144).** 모든 아티팩트 `meta.json`은 계열을 `model_kind`로 밝힌다 — `lightgbm`(기본,
144 이전 아티팩트에는 키가 없어 그렇게 해석한다) / `dl`. `latest_artifact(models_dir, kind=…)`가 이걸로
거르고 배치의 `--predictor auto`는 `kind="lightgbm"`으로만 부른다. 폴더명 정렬에만 기대면 계열이 섞이는 순간
운영 기본값이 이름 운에 맡겨지기 때문이다. **새 계열을 추가할 때는 `model_kind`를 반드시 쓴다.**

**`required_history_days` 규칙(144).** 예측기는 필요한 과거 일수를 스스로 알린다(lookup·LightGBM 7,
DL은 `seq_days`=14). 배치는 `max(HISTORY_DAYS, predictor.required_history_days)`로 이력 창을 잡고
`meta.history_window_days`에 남긴다. DL은 창이 그보다 짧게 와도 앞쪽이 마스크 0으로 그대로 동작한다.

**결측 내성(143에서 확인).** 배포 세트 모델에 시차 컬럼을 전부 NaN으로 넣으면 lookup 대비 RMSE **−36.6 / −40.7%**,
1주 전만 있으면 −20.8 / −14.9%(`validation/CROWD/recent-source-check/RESULTS.md` 4절). 학습 때 결측을 본 적이 없기 때문이다.
**197부터는 이 붕괴를 lookup 대체가 아니라 라우팅(아래)으로 피한다** — 이력 상태에 따라 처음부터 다른 예측기를 쓴다.
학습 시 시차 마스킹은 144가 다뤘고 198이 입력을 고쳤다 — 채택 구성(V3)은 같은 상황에서 **+1.05 / +1.92%**다
(144 V0은 −7.9 / −3.9였다).

**가용성별 예측기 선택 — 145에서 쌍 부트스트랩으로 판정**(`validation/CROWD/family-check/RESULTS.md` 8절).
같은 시나리오 안에서 계열을 쌍 비교한 결과(날짜 블록 1,000회, 2025 전체 1,992,900행):

| 이력 상태 | 예측기 | GRU − LightGBM RMSE %p [CI 하한] 승/하 |
| --- | --- | --- |
| 완비(`full`) | **LightGBM 유지** | −2.92 [−4.42] / −2.03 [−3.67] — GRU 열세. MAE·등급은 GRU 근소 우위(등급 97.225 vs 97.025)지만 1호선 −9.9%p·5호선 −5.0%p 슬라이스가 교체 기준을 깬다 |
| 결손(`d1_only`·`d7_only`) | **GRU V3** | +10.56 [+8.94] / +11.60 [+9.73] · +25.51 [+22.89] / +20.47 [+17.81]. 휴일 슬라이스 CI 하한만 0 아래(표본 18일) |
| 전무(`no_lag`) | **GRU V3**(143의 lookup 대체 가능) | +38.86 [+35.77] / +44.18 [+40.80], 모든 슬라이스 하한 > 0 |

**단 `no_lag`에서 GRU가 lookup을 "넘는다"고 쓰지 않는다** — 날짜 CI로 보면 시드 3개 중 하나만 하한이 0 위
(+0.35/+1.22)이고 나머지는 0을 포함한다(198의 시드 표준편차 ±1.02보다 날짜 CI 폭 ±1.9%p가 넓다).
채택 근거는 정확도 우위가 아니라 **LightGBM의 −36.6/−40.7%p 붕괴를 피한다**는 것이다.
하루치 CPU 추론은 GRU 0.23초 / LightGBM 0.03초(5,460행)로 운영 기준(10분)에 무관하다.

### DL 배포판 — 이름 정렬로 고르지 않는다(197 B-3)

`--predictor dl`(과 라우팅이 `dl`을 고르는 모든 경우)은 `latest_artifact(kind="dl")`(폴더명 정렬 최신)을
쓰지 않는다. DL 변형이 18개라 이름 정렬 최신은 채택 구성이 아니라 우연히 이름이 뒤에 오는 다른 변형
(`dl_lstm_s14_noev_s44_…` 등)을 고른다. 대신 `Settings.crowd_dl_artifact`(`app/core/config.py`)로
폴더명을 고정한다.

| 항목 | 값 |
| --- | --- |
| 설정값 | `crowd_dl_artifact: str = "dl_gru_s14_noev_s42_20260914-1358"` |
| 가리키는 아티팩트 | `dl_gru_s14_noev_s42_20260914-1358` — 198 V3 구성(7채널, **정적 이벤트 없음**), 시드 42 |
| 판정 근거 | 198 판정 1·4(이벤트 5열 제거가 `full`·`no_lag` 동시 개선) + 145 family-check(위 표) |
| 실패 동작 | 폴더가 없으면 `FileNotFoundError`(설정값 이름·기대 경로를 메시지에 남김), 폴더는 있는데 `meta.json`의 `model_kind`가 `dl`이 아니면 `ValueError`(설정값이 잘못된 폴더를 가리키는 경우를 잡는다) |

### 가용성별 라우팅 정책 — `app/CROWD/pipeline/routing.py`

운영 코드 반영(197 B부, `predict_day`가 매 날짜 `routing.availability()` → `routing.select()`로 kind를 정한다).
활성 정책은 가용성 축만이라 오늘 한 표는 예측기가 하나로 배정된다(`routing.POLICY`).

| 가용성(`avail`) | 뜻 | 예측기(`pred`) |
| --- | --- | --- |
| `full` | 전날·1주 전 실측 모두 있음 | `lightgbm`(`auto`와 동일 — 최신 lightgbm 아티팩트) |
| `d1_only` | 전날만 있음 | `dl`(`crowd_dl_artifact` 고정 아티팩트) |
| `d7_only` | 1주 전만 있음 | `dl` |
| `no_lag` | 둘 다 없음 | `dl` |

부원(비활성) 규칙 2개(1호선 전용 선형 회귀, 모양 군집 LightGBM)는 `routing.py`의 `POLICY` 목록에 **주석**으로만
남아 있다 — 근거는 있으나 미검증이라 논의 I-1(원인 규명)이 선행돼야 켤 수 있다. `Rule`이 `avail` 외에
`line`·`day_type`·`group`도 받을 수 있어 그 규칙을 켜도 구조를 다시 잡지 않는다(명시 조건이 많은 규칙이 우선).

## 5. 변환 층 산출물 — 배율표도 아티팩트처럼 추적한다

모델만 버전이 있는 게 아니다. **배율표(`data/CROWD/processed/crowd_congestion_calibration.parquet`)는
모든 혼잡도 산출의 승수**라, 이게 바뀌면 같은 모델·같은 승하차에서도 화면 값이 통째로 바뀐다.
그래서 199부터 모델 아티팩트와 같은 수준으로 추적한다 — 옆에 `crowd_congestion_calibration.meta.json`을
동봉하고, 이전 파일은 `data/CROWD/processed/_archive/`로 옮긴다(둘 다 gitignore).

| 항목 | 값(현행) |
| --- | --- |
| 변형 코드 | `branch_anchored-segment1_all` (199 채택 = A1 + B1s + C1) |
| 적합 스냅샷판 | 2025-11-30판(서울 열린데이터광장 OA-12928, 142 §1에서 식별) |
| 승하차 창 | `all` — 2024-01-01 ~ 2026-01-31(762일) |
| 방향 대응 | `congestion.BRANCH_DIRECTION_MAP`(146) — 성수지선 하선→외선 / 신정지선 하선→내선, 분기역 제외 |
| 경계 처리 | B1s — 절단 구간 raw에 경계 유입 상수 주입(`raw_offset` 컬럼), `anchored` 적합·구간 전체 |
| 행 / 결측 | 67,145 / 3,103 |
| sha256 | `f315a207…` (이전 `163b5318…`) |

`meta.json`에 들어가는 키: `ticket, snapshot_release, snapshot_source, label_source, ridership_window,
direction_mapping, boundary_variant, variant, variant_code, rows, ratio_defined, ratio_missing,
diagnostics, previous_sha256, previous_archived_as, generated_at, sha256`.

**언제 다시 만드나** — 새 연도판 스냅샷이 나왔을 때(분기 갱신), 승하차 원천이 연장·개통·집계 정의
변화로 끊겼을 때(142 §4), 적합 규칙을 바꿀 때. 명령은
`python -m DATA_ENGINE.eda.build_congestion_calibration`(변형은 `--variant`, 88 현행 재현은
`--variant current`)이고, 하류 `crowd_congestion_label_calibrated_2024_2026.parquet`도 같이 다시 만든다.

out-of-sample 성능(연도 홀드아웃)은 셀 MAE 2.147(2023→2024) / 1.428(2024→2025)%p, 등급 일치율
96.776 / 97.965%다 — 수치 원본은 `validation/CROWD/calibration-refit/RESULTS.md`(199)와
`calibration-holdout/RESULTS.md`(142).

## 6. 이 코드들이 바뀌는 경우

- 세트 정의가 바뀌면 `FEATURE_SETS`에 **새 이름을 추가**하고 옛 이름은 남긴다(기록·재현). 파생 규칙이 바뀌면 `DERIVED_VERSION`을 올린다.
- 배포 세트 교체는 `train.py` 기본값 + 이 문서 2·3절 + 해당 RESULTS.md 판정이 한 커밋.
- 모델 계열 교체(딥러닝·LLM)는 `predictor.py`에 kind를 추가하는 것이고 세트 코드와는 별개(145 판정 기준: RMSE·MAE 둘 다 +2%p).
