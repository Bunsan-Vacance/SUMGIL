# observability-check

서버·Infra 없이 **로컬에서 Grafana 대시보드 JSON과 프로비저닝을 확정**하는 검증 환경이다 (S15P21A104-341 W1-4).
여기서 굳힌 값(데이터소스 이름·UID·대시보드 UID·지표 이름)이 그대로 `Infra/k8s/ops/` 제안서로 옮겨간다.
`app/ops/`(운영 지표 API)와 `DATA_ENGINE/observability/export_textfile.py`(textfile 지표)가 만드는 모양을
**합성 데이터**로 흉내 내서 패널이 제대로 그려지는지 본다. 실측은 서버에서 24시간 돈 뒤에 따로 한다.

## 구성

| 서비스 | 포트 | 역할 |
| --- | --- | --- |
| grafana (11.6, Infinity 플러그인) | 3000 | 대시보드 4장 + 데이터소스 2개 프로비저닝 |
| prometheus | 9090 | node-exporter 15초 스크레이프, 보존 15일 |
| node-exporter | - | `./textfile/*.prom`을 textfile collector로 노출 |
| (호스트) uvicorn ai-api | 8000 | `/ops/*` — Grafana(Infinity)가 `host.docker.internal:8000`으로 읽는다 |

- 데이터소스 UID: `prometheus`, `infinity-ai`(서버용 `pg-ro`는 `datasources.yml`에 주석 예시만).
- 대시보드(폴더 `SUMGIL 운영`): `sumgil-model-quality`(보드 ②, 9패널), `sumgil-pipeline-health`(보드 ③, 8패널),
  `sumgil-spark-jobs`(보드 ⑤, 7패널), `sumgil-data-quality`(보드 ⑥, 12패널). 텍스트 패널 포함 개수다.
- 정본·`Infra/k8s/ops/` 복사본·버전 핀 정합은 `AI/test/OPS/test_dashboard_consistency.py`가 검사한다. 복사본이 어긋나면 이 테스트가 실패한다.

## 실행 순서

```bash
# AI 루트(AI/)에서
python validation/INFRA/observability-check/fixtures/make_fixtures.py          # 1) 합성 데이터
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000                       # 2) ai-api (별도 터미널)
cd validation/INFRA/observability-check && docker compose up -d                 # 3) 스택
# 4) http://localhost:3000  (admin / admin, 로컬 전용) -> 폴더 "SUMGIL 운영" 4장 확인
docker compose down -v                                                          # 5) 정리(볼륨 포함)
```

- 2)의 `--host 0.0.0.0`은 Linux Docker 엔진에서 컨테이너가 호스트로 들어오려면 필요하다. Docker Desktop
  (Windows/Mac)은 기본 `127.0.0.1` 바인딩으로도 닿는 것을 확인했다.
- 픽스처는 오늘 날짜 기준으로 만든다. **textfile의 시각이 24시간 지나면 "마지막 성공 이후 경과"가 임계를 넘어
  빨강으로 바뀌므로 다시 실행**한다. ops API는 60초 캐시라 픽스처를 다시 만들면 1분 뒤 반영된다.
- 픽스처가 쓰는 곳(모두 gitignore 대상): `AI/data/CROWD/{monitoring,processed/auto,interim/spark_exp}`,
  `AI/models/CROWD/_experiments/auto/auto_synth-*`, 이 폴더의 `textfile/sumgil_*.prom`. 경로는
  `--root`·`--models-root`·`--textfile-dir`로 바꿀 수 있다.
- 보드 ⑥(`data-quality.json`)은 ops API `/ops/data-quality` 계열 6개를 읽는다. 픽스처는
  `monitoring/data_quality/dt=<최근 30일>/part.json`과 `features/dt=<최근 8일>/part.json`을 합성한다
  (이상치 17건·DQ4 하루, 결손 역 3개·DQ1 하루, `schema_ok:false` 하루, 호선 7개 z 추세, 2일은 `z_adjusted` 포함,
  PSI crit 2개(`TD1:lag1d_*`) 하루). **실데이터 사이드카가 이미 있으면** `make_fixtures.py --skip-data-quality`로
  이 합성을 건너뛴다(나머지 보드용 픽스처는 그대로 생성).
- 보드 ⑥ 호선 z "히트맵"은 히트맵 패널이 아니라 `groupingToMatrix`(날짜 x 호선) + 셀 배경색 표다(|z| 2·3 임계).
  이상치 표는 변수 `date`(textbox)를 쓴다. **비우면 API가 422**(`date=` 빈 문자열을 거부)이므로
  `YYYY-MM-DD`를 넣어야 표가 채워진다.
- 보드 ③의 "데이터 품질 경보(최근일)" Stat은 `/ops/data-quality?days=1`의 `alert_count`다.
  R2 입력 드리프트(`drift_latest.json`)를 읽는 API가 없어 R2 자체는 담지 않는다.
- shadow 패널은 상단 변수 `shadow`에 `auto_synth-r2`를 넣으면 채워진다.

## 합성 데이터 주의

- **전부 가짜다.** json은 `"synthetic": true`, `.prom`은 첫 줄 `# SYNTHETIC` 주석 + `.prom.synthetic` 마커 파일.
  대시보드 태그 `synthetic-local`도 로컬판 표시다. 숫자(RMSE·소요 시간·행 수)를 해석·보고에 쓰지 않는다.
- 픽스처에는 일부러 이상 상황을 넣었다: 채점 결측일 1일(선 끊김), availability 3종, 게이트 수락·거절 각 1건,
  러너 실패 run 1건, 검증 실패 Spark run 1건, textfile 잡 3개(정상·rc 99·실패+마지막 성공 40시간 전).

## 서버로 옮길 때 바꾸는 값

| 항목 | 로컬 | 서버 |
| --- | --- | --- |
| Infinity URL (`infinity-ai`) | `http://host.docker.internal:8000` | AI 서비스 내부 주소 + `/ai` (예: `http://ai-service:8000/ai`). `allowedHosts`도 같이 |
| Prometheus URL (`prometheus`) | `http://prometheus:9090` | 클러스터 내 Prometheus 서비스 주소 |
| `GF_SERVER_ROOT_URL` / `GF_SERVER_SERVE_FROM_SUB_PATH` | 미사용(루트 경로) | `https://<도메인>/grafana/` / `true` |
| `GF_SECURITY_ADMIN_PASSWORD` | `admin` (로컬 전용) | Secret으로 주입, 하드코딩 금지 |
| PostgreSQL `pg-ro` | 없음 | `datasources.yml` 주석 예시를 풀고 읽기 전용 계정 비밀번호는 Secret |
| textfile 경로 | `./textfile` 볼륨 | 서버의 `SUMGIL_TEXTFILE_DIR`과 node-exporter `--collector.textfile.directory`를 일치 |
| Prometheus `honor_labels` | `true` | **반드시 `true`** — 아래 참고 |
| UID들 | `prometheus`·`infinity-ai`·`sumgil-*` | **바꾸지 않는다**(대시보드 JSON이 참조) |

**`honor_labels: true`가 필수다.** textfile 지표는 자체 라벨 `job="crowd_*"`를 갖는데, 스크레이프 잡 라벨(`job=node`)과
충돌하면 기본 설정에서는 `exported_job`으로 밀려나 대시보드의 `{{job}}` 범례가 모두 `node`로 나온다. 로컬에서 실제로 겪어
`prometheus.yml`에 반영했다. 서버 Prometheus가 다른 방식(ServiceMonitor 등)이면 같은 효과를 내야 한다.

## 알려진 한계

- **디스크 게이지(`node_filesystem_avail_bytes{mountpoint="/"}`)는 Docker Desktop(WSL2)에서 비어 있다.**
  node-exporter 컨테이너가 `/` 마운트를 보지 못한다(호스트 루트를 마운트해도 VM에 `/` 항목이 없음 확인). 서버(Linux)에서
  확인할 항목이다.
- `shadow` 변수가 비어 있으면 shadow 표는 API가 `source=shadow:`를 422로 거부해 오류로 표시된다(안내 텍스트 패널에 명시).
- 대시보드 JSON 렌더링(색 임계, Partition by values 시리즈 분리, XY chart)은 로컬에서 쿼리 응답까지만 확인했고
  화면 렌더링은 Grafana UI로 직접 봐야 한다.
- 쿼리 컬럼 순서: Infinity 백엔드 파서가 컬럼을 이름순으로 돌려주므로 XY chart는 x/y를 `manual`로 지정했다.
- `/ops/jobs`는 러너 단계 rc·초만 담는다. 잡 종료 시각 기준 경과는 Prometheus textfile(보드 ③ 상단)을 쓴다.
- Prometheus 데이터는 컨테이너 볼륨이라 `down -v`로 사라진다. 실측 `RESULTS.md`는 서버 24시간 뒤에 만든다.
