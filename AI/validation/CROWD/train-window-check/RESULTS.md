# 227 — 학습 구간 확장(2022~) · 연도 표본 가중 · 기상 5열 검증

**질문**: (1) 배포 세트에 기상 관측 5열(`temp_c, precip_mm, wind_ms, humidity_pct, snow_cm`)을 더하면 2025 평가에서 유의하게
나아지는가. (2) 학습 창을 2022~2024로 넓히면 나아지는가 — 평탄 풀링과, 회복기 연도를 가중(2022 0.25 · 2023 0.5 · 2024 1.0)한
경우를 따로 본다.

**답(1) 기상 — 기각.** 관측 기상(상한)을 넣어도 `full` RMSE −0.63/−0.18%p(하차/승차, CI 상한 +0.04/+0.40), `d7_only` ±0.1%p, MAE는 전 시나리오
−1~−2%p **악화**. 이득은 시차가 전혀 없는 `no_lag`에서만 +1.96/+1.53%p(CI 하한 +1.46/+1.02)이고 주말(일 +1.4/+1.8, 토 +0.5/+1.4)에 몰려
있으며 평일은 −1.2/−1.0%p 손해다. 사전 기준(`full`·`d7_only`·`no_lag` 모두 CI 하한 > 0, +1%p 이상)에 세 시나리오 중 하나만 들어 **미채택**.
예보 피드까지 놓고 배포에 넣을 근거는 없다 — 관측 기상으로도 이 정도면 예보로는 더 못 준다(2절). 2호선 슬라이스도 전체와 같은 모양이라
2호선 전용 모델 후속은 열지 않는다(5절).

**답(2) 창 확장 — 기각, 연도 가중으로도 못 살린다.** 2022~24 평탄 풀링은 lookup −12.97/−13.90%, 마스킹 LightGBM `full` −2.29/−2.65,
`d7_only` −4.63/−4.17, `no_lag` −13.94/−14.92%(전부 CI 상한 < 0). 연도 가중(2022 .25 · 2023 .5)은 손해를 **절반으로 줄이지만 방향을 못 바꾼다** —
lookup −5.26/−5.87, `full` −1.35/−1.19(CI 상한 −0.78/−0.56), `d7_only` −2.63/−2.41, `no_lag` −5.73/−6.40. 평탄 → 가중 → 2024 단독이 모든 지표에서
단조라 가중을 더 탐색할 근거가 없다(가중 → 0이면 2024 단독과 같아진다). 배포 학습 창은 **2024(+2025 최종 fit) 유지**. 유일한 예외는 6호선(`full`
+1.1~+1.3%p, 두 창 모두)이며 관찰로만 남긴다(4.3절).

**왜 이렇게 나눴나**: lookup은 요일유형×역×시간대 **평탄 평균**이고 잔차 LightGBM 피처는 이벤트·시차뿐이라 연도·추세 항이 없다.
연도를 늘리면 추세가 아니라 옛 수준으로 끌린 평균이 된다 — 145 후속(`masking-check/RESULTS.md` 13·17절)이 2023 추가로
lookup −3.95/−3.52%, 마스킹 LightGBM `full` −0.83/−1.26%, `no_lag` −4.5/−4.0%를 이미 재었다. 그래서 2022 평탄 풀링은 관측 1회로
닫고, 새로 검증하는 것은 **연도 가중**(여러 해를 쓰되 옛 수준에 끌리지 않는 유일한 경로)과 **기상**이다. 데이터 양은 문제가
아니다(연 200만 행, 4년 797만 행) — 문제는 분포의 나이다.

## 0. 실행 조건 (전 후보 공통 — `AI/CLAUDE.md` "모델 비교는 동등 조건에서만")

| 항목 | 값 |
| --- | --- |
| 학습 레시피 | 배포와 동일: 마스킹 `stack`(d7 .5 / no_lag .3 / d1 .2), seed 42, `DEFAULT_PARAMS`, 그룹 없음 |
| 분할 | 2025-01-01. 평가 = 2025 전체 같은 행(표 W는 `window_diff.py`가 행 수 일치를 검증) |
| 이벤트 표 | **전 후보 `crowd_station_events_2022_2025.parquet`**(09-17 축제 파서 재실행 판). 1차 `w2024`(옛 표)만 예외 — 그래서 창 비교 기준은 `w2024b` |
| 시나리오 | `full` · `d7_only` · `d1_only` · `no_lag`(`evaluate_dl.LGB_MASK`). 판정은 라우팅상 LightGBM이 맡는 `full`·`d7_only`·`no_lag` |
| 지표 | 날짜 블록 쌍 부트스트랩 1,000회(seed 0), rel RMSE·MAE %, 95% CI |
| GRU | 티켓 범위 밖(`--no-gru`). 198 본문이 다룬다 |
| 기준 LightGBM(`--lightgbm`) | `festival_selflag_d1sd_d7_resid_20260913-0340`(2024 단독 비마스킹). **생략하면 `latest_artifact` = `…_train2024-2025`가 잡혀 2025 평가에 누수된다** |
| 코드 | 커밋 `388bb9b`(`--year-weights`, 캐시 지문, 기상 세트, 비교 인자) |

후보:

| 라벨 | 학습 창 | 가중 | 피처 세트 | 파생 캐시 |
| --- | --- | --- | --- | --- |
| `w2024` | 2024 | — | 배포 | `derived_2024_2025`(1차, 옛 이벤트 표) |
| `w2024b` | 2024 | — | 배포 | `derived_2024_2025b` |
| `w2024wx`(`weather`) | 2024 | — | 배포 + 기상 5열 | `derived_2024_2025b` |
| `w2022` | 2022~2024 | 평탄 | 배포 | `derived_2022_2025` |
| `w2022w` | 2022~2024 | 2022 .25 / 2023 .5 | 배포 | `derived_2022_2025w`(가중 lookup 기준) |

## 1. 데이터 — 4년 패널을 지으며 드러난 것

패널 `crowd_panel_2022_2025.parquet` **7,970,500행**(2022-01-01~2025-12-31, 역 284개, 시간대 20개). 승하차 interim은 2022-01부터 있었고
2022 CSV(`…_20221231.csv`, 199,080행)는 파서에 이미 연결돼 있어 `build_crowd_panel --start 2022-01-01`로 바로 지어졌다.

| 연도 | 행 | 역 | 승하차 결측 | 기상 결측 | 경기(`game_count` 합) | 축제(`festival_count` 합) |
| --- | --- | --- | --- | --- | --- | --- |
| 2022 | 1,990,800 | 279 | 0.001% | 100% | 528 | 804 |
| 2023 | 1,992,700 | 282 | 0 | 99.99% | 534 | 557 |
| 2024 | 1,994,100 | 273 | 0 | 0 | 513 | 2,047 |
| 2025 | 1,992,900 | 273 | 0 | 0.01% | 515 | 8,082 |

- **기상은 2024~만 있다**(`asos_hourly.parquet`이 CSV만 읽고, 2022~23 백필은 parquet). 배포 세트·창 후보는 기상을 안 써 무관하고,
  기상 후보는 2024 학습이라 영향 없다. 2022~23 기상이 필요한 조합(`w2022wx`)은 이번에 하지 않았다.
- **경기 일정은 연도별로 고르다**(2022-02-19~). 09-17에 `parsers_sports → join_kbo_attendance → filter_kleague_seoul_metro` 재실행분.
- **축제 파서를 다시 돌렸다** — interim `festival_capital.parquet`이 09-10 판(775행)이라 09-16에 추가된 2022 CSV(1,140행)를 못 봤다.
  재실행 후 1,161행. 그 결과 2022 `festival_count`가 38 → 804로 채워졌다.

### 1.1 축제 재가공이 2024-25 입력도 바꿨다 → 창 비교 기준을 `w2024b`로

새 표의 2024-25 구간을 기존 `crowd_station_events_2024_2025.parquet`와 (date, station_no)로 맞춰 보면 공통 7,958행은 **값이 전부 같고**,
새 표에만 있는 역·일이 **1,148행**(2024 875 · 2025 273) 늘었다. 2024 `festival_count` 합 1,160 → 2,047. 1차 `w2024` 후보(옛 표 학습)와
외부요인이 달라져 "창" 효과와 "표" 효과가 섞이므로, 같은 새 표로 2024를 다시 학습한 `w2024b`를 창 비교의 기준으로 둔다.
`w2024 → w2024b` 쌍차이는 **축제 표 변경 효과**로 따로 기록한다(3절).

### 1.2 결함 — 축제 원천 파일 간 중복으로 `festival_count`가 과대 계산된다 (227 범위 밖, 기록만)

연도별 CSV(`KC_488_WNTY_CLTFSTVL_<연도>.csv`)에 같은 축제가 반복 실리고 `parsers_festival.py`가 파일마다 `festival_id`를 새로 붙여,
interim 1,161행 중 **완전 중복(name·venue·start·end) 417행 = 고유 184건**이다(2024 시작 축제 고유 235 vs 계산 281; 조합 상위 (2024, 2025) 49건,
(2022, 2025) 29건). `map_events_to_stations`는 `festival_id`로만 중복을 걸러 이 경우를 못 잡는다. 전 후보가 같은 입력을 쓰므로 이 안의
비교는 공정하지만, **배포 피처(`festival_count`·`festival_short/long_count`)에도 걸리는 결함**이라 별도 티켓으로 파서 중복 제거 +
재학습 영향 측정이 필요하다. 이번에 파서는 손대지 않았다(배포 입력이 바뀌면 200 승격 절차를 다시 타야 한다).

부수 확인: 원천에 `end_date < start_date`인 행 3건(2022·2023·2024 파일 각 1) — 파서가 그대로 통과시킨다. 2022 파일에는 2024 이후 시작
항목이 없다(2024-25 구간이 늘어난 것은 2022 파일이 아니라 위 중복·재가공 때문).

### 1.3 파생 캐시에 이벤트 표 지문이 없었다 → 캐시 메타 확장

파생 캐시(`crowd_panel_derived_*.parquet`)는 시차 잔차뿐 아니라 이벤트 열도 담는데, 재사용 판단 메타에 이벤트 표 지문이 없어 표만
바뀐 실행이 옛 캐시를 조용히 재사용할 수 있었다. `_cache_meta`에 `lookup_weights`(가중 lookup 파생은 평탄 파생과 다르다)와
`events_file`·`events_mtime`을 넣고 비교를 `_cache_compatible`로 분리했다(커밋 `ca49807`). 옛 메타 + 기본 이벤트 표 조합은 호환으로
유지되고, 표를 명시한 실행만 재빌드된다. 부작용: 다음 `train.py`가 기본 캐시를 한 번 재생성한다(값 동일).

## 2. C-1·D-1 — 기상 5열 (2024 학습 / 2025 평가, 같은 표·같은 캐시)

두 아티팩트 모두 `stack` 마스킹·seed 42·학습 3,988,200행(증강 후)·이벤트 표 `…_2022_2025`·캐시 `…_2024_2025b`. 다른 것은 피처 세트뿐(13열 → 18열).
학습은 각 5분 안, 비교 47초(GRU 생략). 기상 값은 **관측치**(ASOS 108 서울)라 이 표는 "예보가 완벽할 때의 상한"이다.

### 2.1 표 B — `lgbm_masked_weather` − `w2024b_masked-stack` 쌍차이, 전체 (%p, 양수 = 기상이 낫다, 날짜 블록 부트스트랩 95% CI)

| 시나리오 | 하차 RMSE | 승차 RMSE | 하차 MAE | 승차 MAE |
| --- | --- | --- | --- | --- |
| `full` | **−0.63** [−1.30, +0.04] | −0.18 [−0.75, +0.40] | **−1.75** [−2.45, −1.13] | **−1.96** [−2.70, −1.28] |
| `d7_only` | −0.03 [−0.72, +0.69] | +0.11 [−0.58, +0.73] | −1.33 [−2.25, −0.49] | −1.20 [−2.15, −0.28] |
| `d1_only` | +0.60 [+0.18, +0.99] | +0.38 [−0.03, +0.76] | −0.65 [−1.33, −0.03] | −0.66 [−1.43, +0.04] |
| `no_lag` | **+1.96** [+1.46, +2.42] | **+1.53** [+1.02, +2.03] | **+2.38** [+1.50, +3.22] | **+2.80** [+1.82, +3.72] |

lookup 대비 개선율(표 A)로 보면 `no_lag` 1.68/1.76% → 3.63/3.29%, `full` 25.72/23.34% → 25.09/23.17%.

읽기: 시차가 있으면 전날·전주 잔차가 그날의 날씨 효과를 이미 담고 있어 기상 열은 정보를 더하지 못하고 **잡음만 더한다**(MAE 악화가 그 증거 —
작은 오차가 늘었다). 시차가 전부 빠진 `no_lag`에서만 날 단위 정보로 +1.5~2%p를 낸다. 현 라우팅에서 `no_lag`는 LightGBM 몫이지만, 그 상황
(D−1·D−7 실적 모두 없음)은 수집 장애·먼 미래 날짜라 **예보 확보가 가장 어려운 상황**이기도 하다.

### 2.2 슬라이스 — 주말에만 돕고 평일은 해친다

| 요일유형(`full`, RMSE %p) | 하차 | 승차 |
| --- | --- | --- |
| 일요일 | **+1.40** [+0.11, +2.60] | **+1.82** [+0.41, +3.12] |
| 토요일 | +0.52 [−0.94, +2.34] | **+1.37** [+0.24, +2.61] |
| 평일 | **−1.18** [−1.81, −0.59] | **−1.03** [−1.71, −0.40] |
| 휴일(표본 18일) | −2.02 [−6.05, +1.84] | −1.05 [−3.92, +2.04] |

여가 통행(주말)은 날씨에 탄력적이고 통근(평일)은 비탄력적이라는 상식과 맞다. 잔차 모델 피처에 `day_type`이 없어(lookup 키에만 있다) 기상 효과를
요일유형에 따라 나눠 배울 수 없다는 구조적 한계가 평일 손해로 나타난 것일 수 있다 — `weather + day_type` 변형 1회(학습 5분)로 확인 가능하나,
주말 +1.4~1.8%p를 살려도 전체 판정을 뒤집을 크기가 아니라 227 안에서는 하지 않았다(후속 후보).

호선(`full`, RMSE %p 하차/승차): 1호선 −0.95/+0.84 · 2호선 −0.72/−0.35 · 3호선 −0.56/−0.99 · 4호선 −1.14/−1.16 · 5호선 −0.17/+0.41 · 6호선 +0.37/+0.28 ·
7호선 −0.13/−0.57 · **8호선 −2.34/−2.19**. 어느 호선도 CI 하한이 0 위가 아니다.

### 2.3 판정(H3)

사전 기준 "`full`·`d7_only`·`no_lag` 모두 CI 하한 > 0 그리고 +1%p 이상"에 `no_lag`만 든다 → **미채택**. 관측 기상이 상한이므로 예보 기반 재측정도
하지 않는다. 기록으로 남기는 것: (a) `no_lag` 전용·주말 전용으로는 이득이 있다, (b) 살리려면 예보 피드 + `day_type` 상호작용 + `no_lag`
라우팅 분기가 함께 필요해 비용 대비 +1.5~2%p(lookup 대비 개선율 1.7 → 3.5%)는 작다.

## 3. 축제 표 변경 효과 — `w2024 → w2024b` (표 W)

같은 계열(`lgbm_masked_stack`)을 옛 이벤트 표(1차)와 새 표로 학습해 같은 2025 행에서 비교. `lightgbm`(2024 비마스킹, 같은 아티팩트)·`lookup`은
표와 무관해 차이 0 — 표 W가 행 정렬을 제대로 했다는 확인이기도 하다.

| `full` 전체(rel RMSE %, 양수 = 새 표가 낫다) | 하차 | 승차 |
| --- | --- | --- |
| `lgbm_masked_stack` | −0.02 [−0.09, +0.06] | −0.10 [−0.21, +0.01] |

다른 시나리오의 전체 슬라이스도 ±0.11% 안(`d7_only` +0.03/+0.09, `d1_only` −0.11/−0.03, `no_lag` +0.07/+0.06), 호선·요일유형 슬라이스까지 넓혀도
±0.5% 안(1호선 `d1_only` 하차 −0.47 [−0.52, −0.42]가 가장 큼). **축제 표 변경은 결과를 흔들지 않는다** — 1.2절의 중복 결함이 배포 모델
성능에 미치는 영향도 이 크기일 가능성이 높다(파서 수정 뒤 재측정으로 확정할 것).

## 4. C-2·D-2 — 창 확장·연도 가중 (표 W, 기준 `w2024b`)

`w2022`·`w2022w` 둘 다 2022-01-01~2024-12-31 학습(증강 후 11,955,160행), 같은 이벤트 표, 시나리오·마스킹·시드 동일. 다른 것은 **연도 가중 유무**뿐이다
(`w2022w`: lookup 가중 평균 + LightGBM `sample_weight`, 2022 0.25 · 2023 0.5 · 2024 1.0). 파생 캐시는 lookup에 따라 따로 만들었다(`…_2022_2025`,
`…_2022_2025w`). 학습 각 1분 안, 4년 파생 캐시 각 1분 안, 비교 63·66초.

가중이 실제로 들어갔는지: lookup 표의 평균 수준(공통 21,840셀)이 2024 단독 641.2명 / 가중 620.9명 / 평탄 602.2명(승차) — 가중판은 옛 수준으로
끌리는 정도가 절반이다. 2022~23 역 집합(279·282)이 2024~25(273)보다 넓어 lookup 행은 22,380이지만 평가는 2025 행이라 무관.

### 4.1 표 W — 전체, rel RMSE % (양수 = 넓힌 쪽이 낫다, 같은 2025 행, 날짜 블록 부트스트랩 95% CI)

| 시나리오 | 계열 | `w2024b → w2022` 평탄, 하차 | 승차 | `w2024b → w2022w` 가중, 하차 | 승차 |
| --- | --- | --- | --- | --- | --- |
| `full` | `lgbm_masked_stack` | **−2.29** [−3.07, −1.50] | **−2.65** [−3.47, −1.83] | **−1.35** [−1.89, −0.78] | **−1.19** [−1.78, −0.56] |
| `d7_only` | `lgbm_masked_stack` | **−4.63** [−5.72, −3.53] | **−4.17** [−5.17, −3.13] | **−2.63** [−3.32, −1.92] | **−2.41** [−3.09, −1.70] |
| `d1_only` | `lgbm_masked_stack` | −0.59 [−1.34, +0.15] | −2.58 [−3.34, −1.81] | +0.52 [+0.02, +1.05] | −1.12 [−1.71, −0.54] |
| `no_lag` | `lgbm_masked_stack` | **−13.94** [−15.51, −12.40] | **−14.92** [−16.45, −13.37] | **−5.73** [−6.51, −4.95] | **−6.40** [−7.19, −5.59] |
| (전 시나리오) | `lookup` | **−12.97** [−14.43, −11.56] | **−13.90** [−15.28, −12.53] | **−5.26** [−5.97, −4.54] | **−5.87** [−6.56, −5.15] |

MAE도 같은 방향(평탄 `full` −1.99/−2.88, 가중 −0.81/−1.23). 145 후속의 2023-24 창(lookup −3.95/−3.52, `full` −0.83/−1.26)에 2022를 더 얹으면
lookup 손해가 −13~−14%로 커진다 — 2022 상반기가 거리두기·마스크 의무 해제 전이라 회복기 중에서도 가장 낮은 수준이기 때문이다.

### 4.2 읽기

- **lookup이 끌려 내려가고, 시차가 그 대부분을 흡수한다.** 평탄 풀링에서 lookup −13%인데 `full` LightGBM은 −2.3~−2.7%다 — 전날·전주 잔차 시차가
  수준 이동을 거의 되돌린다. 시차가 없는 `no_lag`는 lookup에 그대로 묶여 −14~−15%. `d7_only`는 그 중간(−4~−5%).
- **가중은 손해를 절반으로 줄이지만 부호를 못 바꾼다.** lookup −13 → −5, `full` −2.5 → −1.3, `no_lag` −14.5 → −6. 평탄 → 가중 → 2024 단독이
  모든 시나리오·양쪽 타깃에서 **단조**라(가중 → 0이면 2024 단독) 가중값을 더 탐색해도 2024 단독을 넘어설 지점이 없다. "옛 연도가 패턴을 보강한다"는
  기대는 어느 슬라이스에서도 나타나지 않았다(6호선 예외, 4.3절).
- `d1_only` 하차만 가중에서 +0.52 [+0.02, +1.05] — CI가 0에 붙어 있고 승차는 −1.12라 판정에 넣지 않는다. `d1_only`는 현 라우팅에서 GRU 몫이다.

### 4.3 슬라이스 — 6호선만 반대

`full`, `lgbm_masked_stack`, RMSE % (하차/승차):

| 창 | 1호선 | 2호선 | 3호선 | 4호선 | 5호선 | **6호선** | 7호선 | 8호선 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 평탄 | −3.27/−5.86 | −3.30/−2.94 | −2.43/−2.38 | −1.68/−1.04 | −1.37/−0.85 | **+1.32/+1.15** | −0.66/−1.19 | −3.50/−4.21 |
| 가중 | −3.95/−3.91 | −1.55/−1.08 | −1.09/−1.11 | −0.27/+0.18 | −0.96/−0.22 | **+1.14/+1.29** | +0.04/−0.39 | −1.70/−2.31 |

6호선은 배포 모델이 가장 약한 호선(93: lookup 대비 개선이 다른 호선보다 작고 응암 순환·연신내 결번이 걸림)이라 이력이 늘어나는 것이 도움이 되는
유일한 곳이다. 호선별 학습 창을 따로 두는 설계는 lookup 키 구조상 가능하지만 +1%p를 위해 아티팩트 구조를 바꿀 가치는 없다 — 관찰로 남긴다.
요일유형은 평일·토·일 모두 손해(평탄 −2.2~−3.7, 가중 −0.2~−2.5), 휴일은 표본 18일이라 CI가 ±4%p로 판정 불가.

### 4.4 판정(H1·H2)

- **H1**: 평탄 풀링은 `lgbm_masked_stack`·`lookup` 모두 CI 상한 < 0(`d1_only` 하차 하나만 +0.15) → **손해 확정**.
- **H2**: 가중 창은 `full`·`d7_only`·`no_lag` 세 시나리오 모두 CI **상한**이 0 아래 → 채택 기준(하한 > 0)에 어느 것도 못 든다 → **미채택**.
  배포 학습 창 2024(+2025 최종 fit) 유지. `dataset.py`의 `PANEL_NAME`/`SPLIT_DATE`, `config.py` 아티팩트 고정은 변경하지 않는다.

## 5. 호선 슬라이스 — 2호선

사전 규칙: 전체 슬라이스에선 효과가 없는데 2호선만 CI 하한 > 0이거나 두 값이 1%p 이상 벌어지면 2호선 전용 쌍(기상 유·무)을 후속으로 연다.

**기상(2절)**: 2호선 `full` −0.73/−0.35, `d7_only` +0.15/+0.19, `no_lag` +1.36/+0.51 — 전체(−0.63/−0.18, −0.03/+0.11, +1.96/+1.53)와 같은 모양이고
1%p 이상 벌어진 칸이 없다. **2호선 전용 모델 후속은 열지 않는다.** 상/하행은 모델 축이 아니라 재귀식·배율표 층(`congestion.py`)의 몫이라 이 실험으로
정의되지 않는다(93 (D) 결정 유지).

**창·가중(4절)**: 2호선 `full` 평탄 −3.30/−2.94, 가중 −1.55/−1.08 · `d7_only` −5.75/−4.77, −3.00/−2.42 · `no_lag` −17.85/−17.39, −8.13/−8.03 —
전체보다 오히려 손해가 크다(2호선 순환선의 2022 회복 폭이 컸다는 뜻). 2호선 전용 후속 없음.

## 6. 판정 (사전 고정 기준 → 결과)

| 가설 | 기준 | 결과 | 판정 |
| --- | --- | --- | --- |
| H1 2022~24 평탄 풀링 | `lgbm_masked_stack`·`lookup` CI 상한 < 0이면 손해 | 전 시나리오 상한 < 0(`d1_only` 하차 +0.15 하나 제외), lookup −13/−14% | **손해 확정** |
| H2 연도 가중(.25/.5/1) | `full`·`d7_only`·`no_lag` 모두 CI 하한 > 0, 어느 것도 < −1%p 아님 | 세 시나리오 모두 CI **상한** < 0(`full` −1.35/−1.19) | **미채택** — 창 2024(+2025) 유지 |
| H3 기상 5열(관측 = 상한) | 세 시나리오 모두 CI 하한 > 0 그리고 +1%p 이상 | `no_lag`만 +1.96/+1.53, `full` −0.63/−0.18, MAE 전부 악화 | **미채택** — 예보 기반 재측정도 하지 않음 |

**반영**: 프로덕션 변경 없음(`PANEL_NAME`·`SPLIT_DATE`·`crowd_*_artifact` 그대로). 코드로 남는 것은 `--year-weights` 옵션·캐시 지문·기상 실험 세트·
비교 인자이며 전부 기본값에서 비활성이다. `MODEL_REGISTRY.md`는 채택이 없어 갱신하지 않고, 이 문서와 `validation/CROWD/README.md` 행이 근거다.

**후속 후보(티켓 없음)**: (a) 축제 원천 파일 간 중복 제거(1.2절) → 배포 `festival_count` 재계산·영향 측정 — 3절 크기(±0.5%)면 재학습 불필요.
(b) `weather + day_type` 상호작용 1회(2.2절) — 주말 +1.4~1.8%p를 살릴 수 있는지, 예보 피드가 다른 이유로 생기면 그때. (c) 6호선 이력 확장(4.3절) —
6호선 고유 피처(93 후속) 쪽이 먼저다.

## 7. 재현

```
# A. 데이터
python -m DATA_ENGINE.eda.build_crowd_panel --start 2022-01-01 --end 2025-12-31
python -m DATA_ENGINE.eda.parsers_festival
python -m DATA_ENGINE.eda.map_events_to_stations --panel crowd_panel_2022_2025.parquet
# C-1
python -m app.CROWD.pipeline.train --mask-mode stack --split-date 2025-01-01 --out-root models/CROWD/_experiments/window227 \
  --panel crowd_panel_2024_2025.parquet --events crowd_station_events_2022_2025.parquet --derived-cache crowd_panel_derived_2024_2025b.parquet --name w2024b_masked-stack
python -m app.CROWD.pipeline.train --mask-mode stack --split-date 2025-01-01 --out-root models/CROWD/_experiments/window227 \
  --panel crowd_panel_2024_2025.parquet --events crowd_station_events_2022_2025.parquet --derived-cache crowd_panel_derived_2024_2025b.parquet \
  --feature-set festival_selflag_d1sd_d7_resid_weather --name w2024_weather_masked-stack
# D-1
python validation/CROWD/masking-check/compare.py --window w2024b --no-gru --lightgbm models/CROWD/festival_selflag_d1sd_d7_resid_20260913-0340 \
  --masked stack=models/CROWD/_experiments/window227/w2024b_masked-stack \
  --panel crowd_panel_2024_2025.parquet --events crowd_station_events_2022_2025.parquet --derived-cache crowd_panel_derived_2024_2025b.parquet
python validation/CROWD/masking-check/window_diff.py --base w2024 --other w2024b --out data/CROWD/interim/validation/masking_check/w2024b/window_diff_W.md
python validation/CROWD/masking-check/compare.py --window w2024wx --no-gru --lightgbm models/CROWD/_experiments/window227/w2024b_masked-stack \
  --masked weather=models/CROWD/_experiments/window227/w2024_weather_masked-stack --extra-cols temp_c precip_mm wind_ms humidity_pct snow_cm \
  --panel crowd_panel_2024_2025.parquet --events crowd_station_events_2022_2025.parquet --derived-cache crowd_panel_derived_2024_2025b.parquet
# C-2 (가중 lookup 파생은 캐시를 따로 — --year-weights는 --derived-cache 필수)
python -m app.CROWD.pipeline.train --mask-mode stack --split-date 2025-01-01 --out-root models/CROWD/_experiments/window227 \
  --panel crowd_panel_2022_2025.parquet --events crowd_station_events_2022_2025.parquet --derived-cache crowd_panel_derived_2022_2025.parquet --name w2022_masked-stack
python -m app.CROWD.pipeline.train --mask-mode stack --split-date 2025-01-01 --out-root models/CROWD/_experiments/window227 \
  --panel crowd_panel_2022_2025.parquet --events crowd_station_events_2022_2025.parquet --derived-cache crowd_panel_derived_2022_2025w.parquet \
  --year-weights 2022:0.25,2023:0.5 --name w2022w_masked-stack
# D-2 (표 W 기준 w2024b; 비교의 단독 lookup도 같은 가중으로 fit)
python validation/CROWD/masking-check/compare.py --window w2022 --no-gru --lightgbm models/CROWD/festival_selflag_d1sd_d7_resid_20260913-0340 \
  --masked stack=models/CROWD/_experiments/window227/w2022_masked-stack \
  --panel crowd_panel_2022_2025.parquet --events crowd_station_events_2022_2025.parquet --derived-cache crowd_panel_derived_2022_2025.parquet
python validation/CROWD/masking-check/compare.py --window w2022w --no-gru --lightgbm models/CROWD/festival_selflag_d1sd_d7_resid_20260913-0340 \
  --masked stack=models/CROWD/_experiments/window227/w2022w_masked-stack --year-weights 2022:0.25,2023:0.5 \
  --panel crowd_panel_2022_2025.parquet --events crowd_station_events_2022_2025.parquet --derived-cache crowd_panel_derived_2022_2025w.parquet
python validation/CROWD/masking-check/window_diff.py --base w2024b --other w2022  --out data/CROWD/interim/validation/masking_check/w2022/window_diff_W.md
python validation/CROWD/masking-check/window_diff.py --base w2024b --other w2022w --out data/CROWD/interim/validation/masking_check/w2022w/window_diff_W.md
# 노트북(그림만, 재계산 없음)
python validation/CROWD/train-window-check/_build_notebook.py
```
표 원본 `data/CROWD/interim/validation/masking_check/{w2024b,w2024wx,w2022,w2022w}/`, 아티팩트 `models/CROWD/_experiments/window227/`.
