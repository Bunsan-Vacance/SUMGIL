# CROWD

혼잡도 도메인의 검증·PoC 코드. `validation/README.md`의 컨벤션을 따른다. 수치 원본은 각 폴더의
`RESULTS.md`, 팀 요약은 Notion `실험실 / [CROWD] 혼잡도` 하위 페이지.

| 폴더 | 티켓 | 무엇을 검증했나 |
| --- | --- | --- |
| `baseline-check/` | 87·89·90 | lookup 베이스라인, 후보 모델·피처 세트 비교, 배포 세트 확정, 등급 전달·임계치 민감도 |
| `time-resolution-check/` | 135 | 1시간→30분 비중 홀드아웃, 30분→열차 배분의 내부 일관성 |
| `split-check/` | 93 | 전역 vs 호선별·6호선 분리·군집별 fit, 같은 요일유형 시차 세트(B′·B″), 서울역 제외 참고, 방향 진단. 결과 노트북 `split_check.ipynb`(출력 포함) |
| `recent-source-check/` | 143 | D−1 승하차 원천(`getStnPsgr`) 하루치 점검(커버리지·심야 귀속·규모), 시차 피처 결측 시 배포 모델 퇴화(lookup보다 −37%) → 수집기 필요 판정 |
| `dl-resid-check/` | 144 | 딥러닝 시계열(GRU) 잔차 모델 — 이력 절단 증강 학습, 2025 이력 가용성 4시나리오(`full/d7_only/d1_only/no_lag`) × 3계열 비교. `full`은 LightGBM에 RMSE로 지지만 이력이 없을 때 붕괴하지 않는다(등급 일치율 lookup 수준 유지). 결과 노트북 `dl_resid_check.ipynb`(출력 포함) |
| `dl-input-check/` | 198 | GRU 입력 설계 변형 4안(base·neighbor·events_hist·no_events) × 시드 3회 × 손실 δ 1회. **정적 이벤트 5열이 원인이었다** — 빼면 2025 `full` RMSE 개선율이 시드 평균 +8.29 → +20.17(승), `no_lag`이 −8.13 → +1.05로 lookup을 넘고 2호선 열세(−6.16)도 +21.7로 뒤집힌다. 등급 일치율 96.854%로 LightGBM 초과. 채택 안이 `train_dl` 기본값. **후속 6회**(LSTM × V3 3시드 · 이벤트 `log1p_max` 인코딩 3시드): 계열은 `full` 승차 0.11%p 차이로 구분 불가(gru 유지), 인코딩을 고치면 V0의 붕괴·시드 불안정이 사라지지만(+8.29 ± 7.04 → +19.58 ± 0.71) V3를 넘지 못해 기본값 유지 — **이벤트는 인코딩과 무관하게 이득이 없다**. 결과 노트북 `dl_input_check.ipynb`(출력 포함) |
| `sim-eval/` | 92 | 시뮬레이션 정답 위 열차·5분 단위 예측기 비교, 생성기 가정 민감도, 모델 계열(LightGBM·Chronos·LLM) 비교. 결과 노트북 `sim_eval.ipynb`(출력 포함) |

`AI/README.md` §2.1의 **착석 기회 지수**(혼잡도% → 착석 확률 변환) PoC는 아직 이 폴더에 없다.

## 혼잡도 스냅샷 EDA는 여기 없다

이전에 `crowd-snapshot-eda/`(파서 + EDA 계획)가 이 폴더에 있었지만,
`AI/DATA_ENGINE/eda/{parsers_crowd.py, analysis_crowd.py, report_crowd.py}`로 이관했다 —
원본 파싱 → 프로파일/결측/이상치 분석 → 리포트 생성은 모델 PoC가 아니라 `DATA_ENGINE/`이
맡는 "원천 데이터 수집·EDA" 활동이라서다(`AI/CLAUDE.md` 참고). 따릉이·날씨 EDA도 처음부터
`DATA_ENGINE/eda/`에 있다.

혼잡도 데이터의 "대표 1주 스냅샷"(날짜 컬럼 없음, 일 단위 시계열 아님) 특성과 이후 단계
(`CardSubwayTime` 동적 신호 확보 → 보정계수 → 외부요인 상관) 계획은
[`AI/DATA_ENGINE/README.md`](../../DATA_ENGINE/README.md)와 `reports/crowd_eda.md`(생성 산출물)를
참고한다.
