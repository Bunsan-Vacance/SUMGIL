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

## 재학습 러너(run.py)

systemd 타이머가 부르는 단일 러너다(Airflow 없음). 요청 파일(R1'/R3)·달력 R3·`--force` 중 하나가
있을 때만 돌고, 단계마다 기존 CLI를 subprocess로 부른다. 결과는 `retrain_state.json`의
`runs[-1].steps`에 `{step, rc, sec, detail}`로 쌓인다. **자동 승격은 없다.**

| # | 단계 | 하는 일 | 실패 시 |
| --- | --- | --- | --- |
| 1 | `short_circuit` | 유효한 요청 파일·R3 due(이번 달 후보 없을 때)·`--force`가 없으면 skip | 99(skip) |
| 2 | `guard` | 야간창 KST 21:00~08:00(03:00~03:30 제외), `bike-realtime-reprocess.service` 비활성, 디스크 여유 10GB | 창·재처리는 99, 디스크는 1 |
| 3 | `build_panel` | Spark 롱 재집계(`crowd_panel_rebuild`, `processed/auto/<run>/panel_<run>.parquet`) | 중단 |
| 4 | `to_wide` | 롱 → 와이드(`build_crowd_panel`, 2024-01-01~D-1, `auto/<run>/panel_wide.parquet`) | 중단 |
| 5 | `events` | 이벤트 매핑(`map_events_to_stations`, `auto/<run>/events.parquet`) | 중단 |
| 6 | `train` | `train.py`(`festival_selflag_d1sd_d7_resid`, mask stack, split D-28), 피크 RSS 기록(Linux) | 중단 |
| 7 | `gate` | `gate holdout`(후보 대 챔피언, 챔피언 = `CROWD_LGBM_ARTIFACT`) | rc 0·3은 정상, 2는 중단 |
| 8 | `report` | 후보 폴더에 `RETRAIN_REPORT.md` | - |
| 9 | `notify` | Discord 한 줄(`DISCORD_WEBHOOK_URL` 없으면 stdout만) | 알림 실패는 무시 |
| 10 | `mark_done` | 요청 파일 `.done.json`, `last_candidate_date` 갱신, 보존 정책(최신 4 run, shadow 등록 후보 보존) | - |

- 후보 위치: `models/CROWD/_experiments/auto/auto_<run>/`(run 기본값 KST `YYYYMMDD-HHMM`).
- 종료 코드: 0 완료, 99 skip(정상), 그 외 실패 단계의 코드.
- 옵션: `--force`(요청·R3 없이), `--skip-window`(야간창 검사 생략), `--full`(Spark 전 파티션),
  `--dry-run`(명령 문자열만 기록·실행 안 함), `--run ID`, `--python PATH`.
- 수동 실행: `bash scripts/run_crowd_retrain.sh --force` (점검은 `--force --skip-window --dry-run`).
- **첫 달 운영**: `crowd-retrain.timer`는 enable 하지 않고 수동으로 돌려 결과를 사람이 확인한다.
  타이머(`OnCalendar=22:00 KST`, `Persistent=false`, `TimeoutStartSec=5h`) 설치법은
  `scripts/crowd-retrain.service` 머리 주석, 로그는 `logs/crowd_retrain.log`.
- **승격은 사람이 한다**: `RETRAIN_REPORT.md`와 shadow 채점을 보고 채택하면 `promote_artifact`로
  `models/CROWD/`에 올린 뒤 `.env`의 `CROWD_LGBM_ARTIFACT=`를 바꾸고 재시작한다.
- 주의: `gate holdout`은 이벤트 표를 `dataset.EVENTS_NAME`(기본 이벤트 파일)으로 읽는다. 러너가
  만든 `auto/<run>/events.parquet`와 다를 수 있다.

## shadow 예측

게이트를 통과한 후보는 `data/CROWD/monitoring/shadow_candidates.json`(`{"candidates":[{"artifact":...}]}`)에
등록된다. `scripts/run_crowd_shadow_predict.sh`가 후보마다
`CROWD_LGBM_ARTIFACT=<후보 폴더 절대경로>`로 배치 예측을 돌려 `data/CROWD/shadow/<후보명>/`에 쌓는다
(타이머 `crowd-shadow-predict.timer`, 09:50 KST, `Persistent=true`, 로그 `logs/crowd_shadow_predict.log`).
챔피언의 `serving/`과 `score_daily/`는 건드리지 않는다. shadow 채점은 `run_crowd_score_daily.sh`가 챔피언
채점 뒤 후보마다 `score --serving-dir data/CROWD/shadow/<후보명> --out-dir monitoring/score_shadow/<후보명>`으로
따로 돌린다(아카이브는 `monitoring/pred_archive_shadow/<후보명>/`). 28일 뒤
`gate shadow --champion-score-dir monitoring/score_daily --shadow-score-dir monitoring/score_shadow/<후보명>`이
둘을 나란히 읽어 승격 권고를 낸다. 게이트 holdout은 `--events`로 후보 학습에 쓴 이벤트 표를 받는다(러너가 넘김).
