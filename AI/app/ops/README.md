# 운영 지표 API (`app/ops/`)

Grafana Infinity(JSON) 데이터소스가 읽는 **읽기 전용** 운영 지표 API다 (S15P21A104-341).
FE/BE 계약이 아니라 운영자용이라 `SERVING_CONTRACT.md`에는 넣지 않는다.
응답은 평평한 JSON 배열(숫자·문자·null)이고, 파일 시스템의 사이드카 json만 읽는다(parquet은 열지 않는다).

- **보안 전제**: 인증이 없다. 클러스터 내부망(Grafana -> AI 서비스)에서만 닿아야 하고 외부에 노출하지 않는다.
- **경로**: 로컬은 `/ops/...`, 서버는 Ingress가 `/ai`를 붙여 `/ai/ops/...`.
- **캐시**: 엔드포인트·파라미터별 60초 TTL(프로세스 메모리). 디렉터리가 없으면 `[]`(200), 깨진 json은 그 파일만 건너뛰고 `app.ops` 로거 warning.

## 엔드포인트

| 엔드포인트 | 원천 파일 | 필드 |
| --- | --- | --- |
| `GET /ops/score-daily?days=30&source=champion` | `monitoring/score_daily/dt=*/part.meta.json` (`source=shadow:<artifact>`면 `monitoring/score_shadow/<artifact>/dt=*/…`) | `date, source, availability, predictor_version, rows_scored, missing_station_count, boarding_rmse_model, boarding_rmse_lookup, boarding_improvement_rmse_pct, boarding_mae_model, alighting_rmse_model, alighting_rmse_lookup, alighting_improvement_rmse_pct, alighting_mae_model` — 날짜 오름차순, 결측(NaN)은 null |
| `GET /ops/score-daily/by-line?days=30` | 위 champion meta의 `by_line` | `date, line, n, boarding_rmse_model, boarding_improvement_rmse_pct, alighting_rmse_model, alighting_improvement_rmse_pct` — 날짜·노선 오름차순 |
| `GET /ops/gate?limit=10` | `models/CROWD/_experiments/auto/*/gate.json` + `monitoring/shadow_candidates.json` | `run, mode, window_start, window_end, decided_at, accepted, boarding_point_pp, boarding_ci_low_pp, alighting_point_pp, alighting_ci_low_pp, registered_shadow` — `decided_at` 내림차순 |
| `GET /ops/jobs?limit=20` | `monitoring/retrain_state.json`의 `runs[]` | `run_id, status, started_at, finished_at, exit_code, step, step_rc, step_sec` — run x step 한 행, 최근 run 순(`limit`은 run 수) |
| `GET /ops/spark-runs?limit=50` | `data/CROWD/processed/auto/**/meta.json`, `data/CROWD/interim/spark_exp/**/meta.json` | `job, run, generated_at, elapsed_sec, peak_rss_mb, rows, input_partitions, verify_passed, verify_max_abs_err, cores, driver_memory, path` — `generated_at` 내림차순 |

- `days`는 오늘 기준이 아니라 **채점 파티션이 있는 최근 N개 날짜**다(채점이 늦어도 빈 화면이 되지 않는다).
- `source`가 형식에 맞지 않으면 422(`champion` 또는 `shadow:<영숫자·_.->`).
- `gate`의 `run`은 후보 폴더명에서 `auto_`를 뗀 값이다. `registered_shadow`는 폴더명(`auto_<run>`)이 `shadow_candidates.json`의 `artifact`에 있는지다.
- `spark-runs`: `job`은 `processed/auto` 아래는 `panel_rebuild`, `spark_exp/replay_*`는 `replay_kafka`, 그 외 `unknown`. replay meta에는 `generated_at`·`run`·`verify`가 없어 파일 mtime·폴더명·같은 폴더 `compare.json`의 `match`로 대신하고, `rows`는 `events_written`이다.

## Grafana Infinity 설정 예

- 데이터소스: Infinity, Base URL = AI 서비스 내부 주소(예: `http://ai-service:8000/ai`).
- 쿼리: Type `JSON`, Parser `Backend`, Source `URL`, Format `Table`, Method `GET`,
  URL `/ops/score-daily?days=30`. 응답이 배열 그대로라 **Rows/Root selector는 비워 둔다**.
- 시계열 패널은 `date`(또는 `decided_at`, `generated_at`) 컬럼을 Time으로, 지표 컬럼을 Number로 지정한다.
- 히트맵은 `/ops/score-daily/by-line`에서 `date` x `line` x `*_improvement_rmse_pct`를 쓴다.
