# CROWD 재학습 루프 — 예측 아카이브·채점·드리프트

## 목적

서빙 중인 혼잡도 예측을 매일 실측으로 채점하고(모델 대 lookup 개선율), 성능 저하나 달력 조건이
보이면 재학습 요청 파일을 남긴다. 예측 판은 배치가 덮어쓰기 전에 아카이브해 둔다.
오케스트레이터(Airflow 등) 없이 systemd 타이머로 운영한다.

## 구성

| 모듈 | 역할 |
| --- | --- |
| `common.py` | 경로 상수, KST 시간, 원자적 쓰기, JSON 입출력 |
| `archive.py` | serving의 `predictions_<D>.parquet`+meta를 `pred_archive/dt=D/gen=<generated_at>/`로 복사(멱등) |
| `score.py` | D일 예측 판을 D일 실측으로 채점해 `score_daily/dt=D/`에 저장 |
| `stats.py` | 날짜 블록 부트스트랩 등 통계 함수 |
| `drift.py` | R0, R1', R3 판정, `drift_latest.json`과 재학습 요청 파일 작성 |
| `report.py` | 채점 결과와 드리프트를 `SCORE_REPORT.md`로 렌더 |

## 데이터 경로

기준은 `AI/data/CROWD/` 아래다.

| 경로 | 내용 |
| --- | --- |
| `serving/` | 배치가 쓰는 최신 예측 `predictions_<D>.parquet` + `.meta.json` |
| `monitoring/pred_archive/dt=D/gen=<YYYYMMDDTHHMMSS>/` | 아카이브된 예측 판(보존 정책 없음) |
| `monitoring/score_daily/dt=D/` | `part.parquet`, `part.meta.json` 채점 결과 |
| `monitoring/retrain_request.json` | R3가 due일 때 쓰는 재학습 요청(TTL 7일, 만료·완료 시 이름 변경) |
| `monitoring/retrain_state.json` | 재학습 처리 상태 |

## 타이머 설치

서버 예: `/home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI`

```bash
cd /home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI/scripts
for u in service timer; do
  sed -e "s|<REPO_ROOT>|/home/ubuntu/Soomgil-INFRA-ai-data-monitoring|g" \
      -e "s|<VENV_PATH>|/home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI/.venv|g" \
      crowd-score-daily.$u | sudo tee /etc/systemd/system/crowd-score-daily.$u
done
sudo systemctl daemon-reload
sudo systemctl enable --now crowd-score-daily.timer
systemctl list-timers crowd-score-daily.timer
```

- 실행 시각: 매일 14:10 KST(최대 120초 지연). 실측(D-1 수집)이 들어온 뒤를 노린다.
- 로그: `AI/logs/crowd_score_daily.log`(`logs/` 폴더가 없으면 먼저 만든다). 단계마다
  `[score_daily] step=<이름> rc=<코드> sec=<n>` 한 줄이 남는다.

## 수동 실행

```bash
cd /home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI
bash scripts/run_crowd_score_daily.sh                                  # 아카이브, 채점, 드리프트, 리포트 1회
python -m app.CROWD.pipeline.retrain.score --date 2026-09-10 --force   # 특정 날 재채점
```

## 종료 코드(score)

| 코드 | 의미 |
| --- | --- |
| 0 | 새로 채점했거나 전부 이미 채점됨 |
| 99 | 새 채점 없이 보류(`no_actuals`, `no_prediction`, `guard_excluded`)만 있음. 스크립트는 정상 종료로 처리하고 drift, report를 이어서 돈다 |
| 그 외 | 실패. 스크립트가 해당 코드로 중단한다 |

## 드리프트 규칙(drift.py)

- **R0 데이터 보류**: 최근 28일 중 채점 결과가 없는 날이 7일을 넘으면 hold, R1'은 건너뛴다.
- **R1' 성능 경보**: 가용성·타깃별 모델 대 lookup 개선율의 날짜 블록 부트스트랩 CI 상한이 0 미만이면
  경보. 기준값이 있으면 점추정이 기준-`drop_pp`%p 아래인 경우도 경보. 날짜 7개 미만 그룹은 건너뛴다.
- **R3 달력 트리거**: 매달 첫 일요일이고 마지막 후보 이후 채점일이 20일 이상이면 due. 유효한 요청이
  없으면 `retrain_request.json`을 쓴다.
