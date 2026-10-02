# 재학습 파이프라인 P3 — Spark 재집계 잡(`crowd_panel_rebuild`) 규모 스윕 (합성 raw)

관련 티켓: [S15P21A104-340](https://ssafy.atlassian.net/browse/S15P21A104-340) (재학습 루프),
[S15P21A104-339](https://ssafy.atlassian.net/browse/S15P21A104-339) (재학습·관측 파이프라인).
대상: `DATA_ENGINE/spark/jobs/crowd_panel_rebuild.py` (승하차 raw 재집계 -> pandas `to_long`과 같은 롱 패널).
같은 양식·측정 원칙(정확성 먼저, 그다음 시간·메모리)은 `../spark-compare-check/RESULTS.md`를 따른다.

> **이 문서의 모든 수치는 합성 데이터(실 스키마·실 규모) 측정이다.** 로컬에 실데이터(`data/CROWD/`)가
> 없어 실 `getStnPsgr` raw와 같은 스키마·같은 행 규모의 난수 데이터로 쟀다. 값 분포·역 카디널리티가
> 실데이터와 다르므로 절대 시간은 참고치다. **서버(t3.xlarge) 실데이터 실측은 §2.6**(raw 17일, 수정 후 잡, 정확성 통과).

## 한 줄 결론

**합성 raw 기준, 드라이버 수집을 없앤 수정 잡(`0bd24a2`)은 1000일(롱 2,800만 행)까지 완주하고 정확성은 전 셀 `max_abs_err` 0.0이다.
피크 RSS는 270일 3.7GB → 1000일 3.9GB로 규모에 거의 평탄하지만, 처리 시간은 pandas보다 270일 4.0배·1000일 2.8배 느리다.**
수정 전 잡(`toPandas` 수집)은 270일에서 pandas 대비 1.1배로 빠르지만 RSS 6.3GB, 1000일은 3g 힙 OOM·6g `maxResultSize` 초과로 미완주였다(§2.4).
이 잡의 가치는 속도가 아니라 "raw 재집계가 pandas 롱과 같은 값을 낸다"는 독립 검증과 규모에 무관한 메모리 상한이다(§2.5).

## 1. 실험 설계

- **합성 raw**: `gen_raw.py`. 스키마 = 수집기 `RAW_COLUMNS` 13개(값 전부 문자열, `pasngDe`=YYYYMMDD,
  파티션 `dt=YYYY-MM-DD/getStnPsgr.parquet`). 역·호선 조합 700개(1~9호선 + 경의중앙·수인분당·신분당·공항철도·
  경춘·우이신설·김포골드라인, `stnCd`·`stnNo` 유일) x `pasngHr` "0"~"23" x 카드구분 2 x 사용자구분 2
  = **하루 67,200행**. 실 규모 근거 = 수집기 docstring의 "하루 6.3~6.9만 행". 시드 고정(20261002).
- **마스터**: 2024-01-01부터 1000일(~2026-09-26) 생성 후, 스케일 N일 = 마스터의 **끝에서 N일**을
  하드링크한 입력 루트(270일 = 2025-12-31~2026-09-26, 2026 YTD 상당). 셀은 모두 `--full`.
- **pandas 기준**: 파티션별 `to_long` -> concat -> 기준 롱 parquet 저장(= `--verify-against` 입력).
  wall은 읽기+변환+concat+parquet 쓰기 포함. 별도 subprocess.
- **Spark**: `python -m DATA_ENGINE.spark.jobs.crowd_panel_rebuild --full --verify-against <pandas 롱>
  --cores 3 --driver-memory 3g`(서버 설정 미러 local[3]·3g). wall은 subprocess 전체(JVM 기동·검증·
  패널 parquet 쓰기 포함), 피크 RSS는 psutil 0.2초 샘플링 프로세스 트리(JVM 포함).
  잡 내부 `elapsed_sec`는 `job_elapsed_sec`로 따로 남겼다(wall과 1초 안팎 차이).
- **환경**: Windows 11, RAM 63.5GB, conda `SUMGIL`(pyspark 4.2.0, JDK 21), 로컬 실측 1회씩(반복 없음).
- 비교 공정성 주의: Spark wall에는 `compare_frames` 검증 시간이 들어 있고 pandas wall에는 없다
  (운영에서는 검증을 켜지 않으면 그만큼 줄어든다). 셀당 1회 측정이라 5% 안팎 차이는 노이즈로 본다.

## 2. 결과

### 2.1 정확성 — 속도 비교의 전제 (4개 완주 셀 전부 통과)

| 일수 | 롱 행수(pandas) | 롱 행수(Spark) | 행수 일치 | max_abs_err | verify |
| ---: | ---: | ---: | --- | ---: | --- |
| 30 | 840,000 | 840,000 | 일치 | 0.0 | 통과 |
| 90 | 2,520,000 | 2,520,000 | 일치 | 0.0 | 통과 |
| 270 | 7,560,000 | 7,560,000 | 일치 | 0.0 | 통과 |
| 270 (코어 8·6g) | 7,560,000 | 7,560,000 | 일치 | 0.0 | 통과 |
| 1000 (3g) | 28,000,000 | — | 미완주 | — | 검증 단계 도달 못함(§2.4) |
| 1000 (6g) | 28,000,000 | — | 미완주 | — | 검증 단계 도달 못함(§2.4) |

허용 오차 1e-6. 합성 값이 정수라 합산이 정확히 같다(실데이터도 정수 승하차 인원이라 같을 것으로 보이나
이는 합성 기준 관찰이다).

### 2.2 처리 시간 — wall 초, 비율 = Spark / pandas (1보다 작으면 Spark 우세)

| 일수 | raw 행수 | pandas | Spark(local[3]·3g) | 비율 | 판정 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 30 | 2.0M | **5.6초** | 18.9초 | 3.37 | pandas 3.4배 |
| 90 | 6.0M | **15.8초** | 26.8초 | 1.70 | pandas 1.7배 |
| 270 | 18.1M | **46.8초** | 52.2초 | 1.11 | pandas 1.1배(근접) |
| 270, local[8]·6g | 18.1M | 46.8초 | **45.7초** | 0.98 | 동률(노이즈 범위) |
| 1000 | 67.2M | 181.0초 | 미완주(약 85초에 실패) | — | §2.4 |

pandas 세부(compute+쓰기): 30일 4.2+0.3초, 90일 14.0+0.8초, 270일 43.8+2.1초, 1000일 170.1+9.7초.
pandas는 일수에 거의 선형(약 0.17초/일)이다. Spark는 30->90일 +7.9초, 90->270일 +25.4초로
고정비(JVM 기동 약 7초 + 세션)를 빼면 약 0.14초/일로 pandas와 비슷한 기울기다 — 이 규모에서는
파티션 읽기보다 `groupBy`·`toPandas`·검증 쪽이 시간을 쓴다.

### 2.3 메모리 — 프로세스 트리 피크 RSS (MB)

| 일수 | pandas | Spark(3g) | 비고 |
| ---: | ---: | ---: | --- |
| 30 | 291 | 1,795 | |
| 90 | 571 | 3,198 | |
| 270 | 1,365 | 6,293 | 드라이버 3g 설정인데 트리 합 6.3GB(JVM 오프힙·Python 워커·검증용 pandas 로드 포함) |
| 270, local[8]·6g | — | 7,685 | |
| 1000 | 4,620 | 3,704 (실패 시점) | 6g 재시도 5,425(실패 시점) |

**Spark는 이 잡에서 메모리 이점이 없다.** 결과를 `toPandas()`로 드라이버에 모으고 파이썬에서 검증·쓰기까지
하므로 Spark 트리 피크가 오히려 pandas보다 크다(270일 4.6배). 서버 16GB에서 `--verify-against`를 켜면
270일 기준 이미 6GB대다.

### 2.4 1000일 셀 — 실패 원인(원문 stderr 확인)

| 설정 | 결과 | 원인 |
| --- | --- | --- |
| local[3]·3g | exit 1, 약 85초 | `java.lang.OutOfMemoryError: Java heap space` (`collectAsArrowToPython`, 롱 2,800만 행 수집 중) |
| local[3]·6g | exit 1, 약 84초 | `Total size of serialized results of 3 tasks (1026.5 MiB) is bigger than spark.driver.maxResultSize (1024.0 MiB)` |

즉 롱 포맷 전량을 드라이버로 수집하는 현재 구조(`aggregate_long_spark`의 `toPandas`)는 약 2,000만 행대에서
기본 `maxResultSize` 1GiB 벽에 닿는다. 270일(756만 행)은 통과, 1000일(2,800만 행)은 실패하므로 벽은
그 사이다. 이 설계에서 확인하지 못한 것: `maxResultSize`를 올리면 6g로 완주하는지(세션 설정을 바꿔야 해서
`DATA_ENGINE` 수정 금지 규칙에 따라 미실행). 기본 운영 입력(`--years 2026`, 약 270일)은 벽 아래다.
`--full`(전량)·`--base-panel` 없이 3년치를 한 번에 재집계하려면 이 한계를 먼저 풀어야 한다.

### 2.5 수정 후 재측정 — 드라이버 수집 제거(`0bd24a2`, 10-02 오후)

§2.4의 원인(롱 전량 `toPandas`)을 없앴다: 집계·base 유니온(`left_anti`)·중복 키·결측 검사·pandas 대조(full outer join)를 전부 Spark DataFrame으로 처리하고,
쓰기는 `orderBy(KEY_COLS).coalesce(1)` 파티션을 `mapInArrow`로 받아 pyarrow `ParquetWriter`로 단일 파일에 스트리밍한다(Hadoop 네이티브·winutils 불필요).
같은 합성 입력·같은 설정(local[3]·3g)으로 270일·1000일 셀만 재측정했다(`bench.py --only spark_d270,spark_d1000 --force`).

| 일수 | 롱 행수 | pandas | Spark 수정 전 | Spark 수정 후 | 비율(후/pandas) | 정확성(후) |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 270 | 7,560,000 | 46.8초 / 1,365MB | 52.2초 / 6,293MB | **188.8초 / 3,702MB** | 4.03 | 행수 일치, max_abs_err 0.0 |
| 1000 | 28,000,000 | 181.0초 / 4,620MB | 미완주(3g OOM·6g maxResultSize) | **510.4초 / 3,865MB** | 2.82 | 행수 일치, max_abs_err 0.0 |

- **메모리가 평탄해졌다.** 270→1000일(행 3.7배)에서 트리 피크 RSS +163MB. 드라이버 3g 설정 그대로 2,800만 행을 처리한다. 서버 16GB에서 `--full` 전량도 메모리로는 안전하다.
- **시간은 늘었다.** 270일 52→189초. 늘어난 부분은 (가) `coalesce(1)` 단일 파티션을 파이썬 워커 하나가 Arrow 배치로 받아 쓰는 직렬 쓰기, (나) pandas 대조를 드라이버 pandas가 아니라 Spark full outer join(셔플)으로 한 것. 둘의 분해 측정은 하지 않았다.
- **1000일 비율(2.8배)이 270일(4.0배)보다 낫다** — Spark 고정비 비중이 줄고 pandas는 선형으로 늘어서다. 165 벤치의 결론(규모가 커질수록 Spark에 유리, 교차점 수천만 행)과 같은 방향이다.
- 후속 선택지(미구현): 파티션 N개를 병렬로 pyarrow 쓰기 후 row group 단위 순차 병합하면 쓰기 직렬화를 풀 수 있다. 운영 입력(2026 증분 ≈270일, 야간창 1회)에서는 3분이 문제가 아니라 보류.
- 1000일 6g 셀은 3g로 완주하므로 재측정하지 않았다(결과 파일의 `spark_d1000_m6g` 마지막 줄은 수정 전 실패 기록).

### 2.6 서버 실데이터 실측 — J15A104A, raw 17일 (10-02, 커밋 `998ced7`, 관찰)

**실행 조건.** J15A104A(t3.xlarge, 4 vCPU, 15.8GB), 운영 `.venv`(pyspark 4.2.0·pandas 3.0.5·psutil), Java 21. 입력 = 실데이터 raw 17일
(`dt=2026-09-15`~`10-01`, 롱 185,386행) + 고정 패널 `crowd_panel_2024_2025.parquet`(와이드 3,987,000행 → 롱 7,974,000행).
잡은 수정 후 판(`0bd24a2`, `driver_collect=false`), 스크립트 `server/run_server_check.sh`(`7a2da7e`), 각 구성 1회. 원본 `server/results/`.
메모리는 `results.jsonl`의 **프로세스 트리 합산**(JVM 포함)이다. `meta.json`의 `peak_rss_mb`(약 143MB)는 `ru_maxrss`라 드라이버 Python만 잰 값이므로 쓰지 않는다.

| 구성 | 하는 일 | wall | 트리 피크 RSS | 정합성 |
| --- | --- | ---: | ---: | --- |
| pandas 기준선 | 17일 raw → `to_long` 롱 집계 → parquet 쓰기(185,386행) | 3.31초 | 226MB | 기준 |
| Spark local[3]·3g | 집계 + 고정 패널 union(8,159,386행) + 정렬·단일 parquet 쓰기 + pandas 대조 | 99.4초 | 3,864MB | 통과: rows 185,386 = 185,386, max_abs_err 0.0, 중복 키 0 |
| Spark local[2]·2g | 〃 | 110.7초 | 2,970MB | 통과(동일) |

- **이 표는 비교가 아니라 관찰이다.** pandas 셀은 17일 롱 집계만 하고, Spark 셀은 그 위에 800만 행 base 패널 union·전역 정렬·단일 파일 쓰기·대조 조인까지 한다.
  시간 차이(약 30배)는 엔진 차이가 아니라 작업량 차이가 대부분이다. 같은 작업량 비교는 §2.2·§2.5(합성)뿐이다.
- **실데이터 정확성 통과.** 합성에서 0.0이던 오차가 실데이터 17일에서도 0.0, 행수 일치, 유일성 키 중복 0. 이 잡의 목적(독립 검증 경로)은 실데이터로 확인됐다.
- **패널 행수 8,159,386 = 185,386 + 7,974,000.** 7,974,000은 고정 패널 와이드 3,987,000행을 `load_base_panel`이 boarding·alighting 두 행으로 펼친(melt) 롱 행수다.
  2배는 union 결함이 아니라 포맷 변환이고, 최종 중복 키 0이 그것을 뒷받침한다. 스크립트 헤더 주석의 "3,987,000행"은 와이드 기준이라 "롱 7,974,000행"을 병기하도록 고쳤다.
- **2g에서도 완료.** 2코어·2g와 3코어·3g의 시간 차이(+11%)는 각 1회 측정이라 순위 근거로 쓰지 않는다. 운영 설정(3코어·3g)에서 트리 피크 3.9GB로 16GB 서버의 여유 안이다.
- **§2.5(합성, pandas의 2.8~4.0배)와 모순되지 않는다.** 배율은 입력 규모에 따라 달라진다 — 입력이 17일로 작을수록 JVM 기동·세션·base 패널 union·단일 파일 쓰기 같은
  입력 크기와 무관한 고정 비용의 비중이 커진다(**추정**: 단계별 시간을 재지 않았다). 270일·1000일 합성에서는 그 고정 비용이 희석돼 배율이 4.0→2.8로 내려갔다.
- **환경 주의.** 서버 `.venv`의 pandas 3.0.5는 PySpark 4.2.0이 공식 지원하지 않는 버전이라 실행마다 `FutureWarning: PySpark does not yet fully support pandas >= 3.0.0`이 뜬다.
  이번 잡은 Arrow 경로(`mapInArrow`)만 쓰고 결과가 일치했지만, pandas UDF·`toPandas`를 쓰는 다른 잡에서는 문제가 될 수 있다(§4-6).

## 3. 해석

- **교차점**: 이 합성 기준에서 Spark는 어느 규모에서도 pandas를 확실히 앞서지 못했다. 270일(raw 1,800만 행)
  에서 격차가 1.1배로 닫히고 코어 8로 동률이다. `spark-compare-check`의 교차점(2,000만~5,000만 행)과
  같은 구간이다. 결과를 드라이버로 모으는 구조라 그 이후의 이점은 이 잡 형태로는 검증되지 않았다.
- **코어 확장**: local[3]->local[8]에서 52.2->45.7초(12%)로 작다. 서버는 4 vCPU라 8코어 설정을 쓸 수 없다.
- **서버(t3.xlarge 4 vCPU·16GB) 실측(§2.6)**: raw 17일 + 고정 패널 union으로 3코어·3g 99.4초·트리 피크 3.9GB, 2코어·2g에서도 완료.
  실데이터 정확성 0.0 오차. 운영 입력이 연말 약 270일로 늘어도 §2.5의 합성 270일(188.8초·3.7GB)이 상한 참고치다(로컬 22코어 PC 값이라 t3 버스트 CPU에서는 더 걸릴 수 있다).
- **수정 후(§2.5)**: 메모리는 규모에 평탄(3.7~3.9GB)해져 `--full` 전량이 완주하지만 시간은 pandas의 2.8~4.0배다. 속도가 아니라 메모리 상한·전량 재집계 가능성을 산 교환이다.
- **판단**: 현 운영 규모에서 이 잡은 pandas보다 빠르지 않다(수정 후에는 메모리 상한만 유리하다). 이 잡을 두는 이유는 속도가 아니라
  "raw 재집계가 pandas 롱과 같은 값을 낸다"는 독립 검증 경로(정확성 0.0 오차)다.

## 4. 한계

1. 합성 데이터다(값 분포·카디널리티·문자열 길이가 실데이터와 다름). 행수·스키마만 실 규모.
2. 셀당 1회 측정(반복·분산 없음). 합성 스윕은 Windows 로컬. 서버 실측(§2.6)은 raw 17일 1회이며 pandas 셀과 작업량이 달라 비교가 아니라 관찰이다.
3. 270일 입력은 2025-12-31~2026-09-26이라 기본 `--years 2026` 입력과 정확히 같지 않다(전량 `--full` 셀).
4. 수정 전 1000일 셀은 3g·6g 모두 실패했고 `maxResultSize` 상향 시도는 하지 않았다. 수정 후(§2.5)는 3g로 완주했다. 수정 후 셀은 270·1000일만 재측정(30·90일·local[8] 셀은 수정 전 수치).
5. `results.jsonl`의 `spark_d1000`·`spark_d1000_m6g`는 `--force` 재실행으로 두 줄씩 있다(마지막 줄이 유효).
   첫 실행 줄의 `oom` 필드는 없고, 6g 줄의 `oom: false`는 실패 원인이 OOM이 아니라 maxResultSize라서다.
6. 서버 `.venv` pandas 3.0.5 + PySpark 4.2.0 조합은 공식 지원 밖(FutureWarning). 이 잡은 결과가 일치했지만 pandas 의존 경로(`toPandas`·pandas UDF)를 쓰는 잡은 별도 확인이 필요하다.

## 5. 재현

```bash
cd AI
export PYTHONIOENCODING=utf-8
PY=C:/Users/SSAFY/miniforge3/envs/SUMGIL/python.exe
$PY validation/INFRA/retrain-pipeline-check/gen_raw.py --days 1000      # 스크래치에 합성 raw 생성(약 2분)
$PY validation/INFRA/retrain-pipeline-check/bench.py --scales 30,90,270,1000   # resume 지원
$PY validation/INFRA/retrain-pipeline-check/bench.py --scales 1000 --only spark_d1000,spark_d1000_m6g --force
```

원본 수치는 `results.jsonl`(셀당 한 줄, `--force` 재실행은 추가 행). 이 문서와 어긋나면 `results.jsonl`이 맞다.
