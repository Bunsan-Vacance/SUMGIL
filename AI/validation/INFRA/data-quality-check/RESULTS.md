# 데이터 품질·분포 모니터링 — 설계 검증 기록 (보드 ⑥, 합성 검증 단계)

관련 티켓: [S15P21A104-341](https://ssafy.atlassian.net/browse/S15P21A104-341) (관측 스택), 선행 340(Spark 패널 재집계)·339(채점·드리프트).
설계 원본: `.claude/plans/S15P21A104-341-data-quality-design.md`(로컬). 구현: `DATA_ENGINE/spark/jobs/crowd_data_quality.py`,
`app/CROWD/pipeline/retrain/input_drift.py`(+ `drift.py` R2), `app/ops` `/ops/data-quality*` 6개, `validation/INFRA/observability-check/grafana/dashboards/data-quality.json`.

> **상태(2026-10-02): 합성 데이터 검증까지.** 서버(J15A104A)는 10-02가 마지막이라 운영 실행은 없다. 실데이터 17일(raw dt=2026-09-15~10-01)
> 로컬 실행은 서버에서 회수한 파일이 `AI/data/CROWD/`에 들어온 뒤 §3에 채운다. 그전까지 이 문서의 수치는 전부 합성·단위 테스트 값이다.

## 한 줄 결론

**입력 데이터 품질(DQ1~7)과 학습 분포(TD1~5)를 사이드카 json → 읽기 API → Grafana 보드 ⑥으로 잇는 경로가 합성 데이터로 끝까지 동작한다.**
경보 경로 7종(결손 역·NaN/0 비율·호선 총량 z·역×슬롯 이상치·슬롯 분포·스키마·수집 지연)은 주입 테스트로 각각 발화를 확인했다.
임계는 권장값(이상치 |z|>3·상위 50, PSI 0.1/0.25)이며 **실데이터 결과를 본 뒤 최적화**한다 — 특히 DQ4는 셀 수가 많아 상시 경보 위험이 있다.

## 1. 무엇을 검증했나

| 층 | 대상 | 검증 방법 | 결과 |
| --- | --- | --- | --- |
| 생산자(Spark) | `crowd_data_quality.py --rebuild-baseline` / 일별 판정 | 합성 raw(역 3·슬롯 4·구분 4)·와이드 패널(요일유형 3종×10일) 9건 | 기준 평균·표준편차 pandas 손계산과 1e-6 일치, 이상치·결손 역·스키마 변경·수집 지연 주입 시 DQ4·DQ1·DQ6·DQ7 각 발화, 기준 없으면 exit 2 |
| 생산자(pandas) | `input_drift.py` PSI·KS·분위수·가용성, `drift.py` R2 | 순수 함수 26건(동일 분포 PSI≈0, 시프트 > 0.25, KS 알려진 값, R2 양·음성) | 통과. 파생 컬럼 실경로(`add_derived_columns`)는 합성으로 못 탔다 → 실데이터 첫 실행 때 확인 |
| API | `/ops/data-quality`·`/lines`·`/outliers`·`/features`·`/targets`·`/availability` | test/OPS 43건(생산자 형태 json, 구형 형태, 빈 디렉터리, 422, 캐시) | 통과. 보드 검증에서 분위수 키(`"5"` vs `q5`)·가용성 중첩·빈 `date` 불일치 3건을 발견해 소비자 쪽에서 보정 |
| 보드 | `data-quality.json` 12패널 + 보드 ③ 품질 경보 Stat | 로컬 compose(Grafana 11.6·Prometheus 3.5) 로드, 패널 쿼리 11건 `/api/ds/query` | 4장 로드, 11건 200(이상치 표는 `date` 변수 필요 → API 보정으로 해소). 화면 렌더링은 눈으로 미확인 |

## 2. 합성 검증 수치(단위 테스트 값, 참고용)

| 항목 | 값 |
| --- | --- |
| 기준 표 행 수(합성) | 72 = 요일유형 3 × 역 3 × 슬롯 4 × 방향 2 |
| 이상치 주입(기준의 10배) | `outlier_count` ≥ 1, `outliers_top[0]` = 주입 셀, `alerts` ⊇ {DQ4} |
| 결손 역 주입 | `missing_stations` = [152], `alerts` ⊇ {DQ1} |
| PSI 동일 분포 / 평균 시프트 | ≈ 0 / > 0.25 |
| 보드 ⑥ 쿼리 응답(합성 30일 픽스처) | data-quality 30행, lines 210행, outliers 17행(경보일), features 12행, targets 32행, availability 8행 |

## 3. 실데이터 17일 실행 — 대기

채울 것: 기준 표 집계 시간·트리 RSS(400만 행 패널), 17일 DQ 요약(결손 역 수·이상치 수 분포·호선 z 범위·slot_js 범위·경보 일수), 피처별 PSI(17일 창, 28일 미만이라 `--window 17`), 타깃 분위수, 가용성 비율,
그리고 **임계 재조정 근거**(DQ4 `outlier_count` 일별 분포 → `outlier_z` 또는 건수 임계). 연도 차이(기준 2024-25 vs 입력 2026)로 DQ3는 `--level-adjust` 전후를 둘 다 기록한다.

실행:
```
cd AI
python -m DATA_ENGINE.spark.jobs.crowd_data_quality --rebuild-baseline --base-panel data/CROWD/processed/crowd_panel_2024_2025.parquet
python -m DATA_ENGINE.spark.jobs.crowd_data_quality --years 2026 --level-adjust
python -m app.CROWD.pipeline.retrain.input_drift --train-panel data/CROWD/processed/crowd_panel_2024_2025.parquet --recent-panel <최근 와이드 패널> --feature-set festival_selflag_d1sd_d7_resid --date 2026-10-01 --window 17
uvicorn app.main:app --port 8000   # 그 뒤 validation/INFRA/observability-check에서 docker compose up -d (픽스처는 --skip-data-quality)
```

## 4. 한계

1. 합성 데이터와 단위 테스트뿐이다. 실데이터·운영 실행 없음(서버 종료).
2. 요일유형은 `calendar.attach_calendar` 규칙으로 4종(평일·토요일·일요일·휴일). 공휴일 표가 로컬에 없으면 요일만으로 판정한다.
3. DQ3는 승차 합만 쓴다(승하차 합산은 이중 계산). DQ7은 파티션 파일 mtime 기준(raw에 `collected_at` 없음).
4. 임계는 권장값. DQ4 상시 경보 가능성, PSI 임계의 적정성은 실데이터 뒤 판단.
5. 보드 화면 렌더(색 임계·groupingToMatrix 표·XY)는 쿼리 응답까지만 확인.
