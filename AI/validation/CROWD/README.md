# CROWD

혼잡도 도메인의 검증·PoC 코드. `validation/README.md`의 컨벤션을 따른다. 수치 원본은 각 폴더의
`RESULTS.md`, 팀 요약은 Notion `실험실 / [CROWD] 혼잡도` 하위 페이지.

| 폴더 | 티켓 | 무엇을 검증했나 |
| --- | --- | --- |
| `baseline-check/` | 87·89·90 | lookup 베이스라인, 후보 모델·피처 세트 비교, 배포 세트 확정, 등급 전달·임계치 민감도 |
| `time-resolution-check/` | 135 | 1시간→30분 비중 홀드아웃, 30분→열차 배분의 내부 일관성 |
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
