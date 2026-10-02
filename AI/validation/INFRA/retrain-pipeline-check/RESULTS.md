# 재학습 파이프라인 P3 — Spark 재집계 잡(`crowd_panel_rebuild`) 규모 스윕 (합성 raw)

관련 티켓: [S15P21A104-340](https://ssafy.atlassian.net/browse/S15P21A104-340) (재학습 루프),
[S15P21A104-339](https://ssafy.atlassian.net/browse/S15P21A104-339) (재학습·관측 파이프라인).
대상: `DATA_ENGINE/spark/jobs/crowd_panel_rebuild.py` (승하차 raw 재집계 -> pandas `to_long`과 같은 롱 패널).
같은 양식·측정 원칙(정확성 먼저, 그다음 시간·메모리)은 `../spark-compare-check/RESULTS.md`를 따른다.

> **이 문서의 모든 수치는 합성 데이터(실 스키마·실 규모) 측정이다.** 로컬에 실데이터(`data/CROWD/`)가
> 없어 실 `getStnPsgr` raw와 같은 스키마·같은 행 규모의 난수 데이터로 쟀다. 값 분포·역 카디널리티가
> 실데이터와 다르므로 절대 시간은 참고치이고, **서버(t3.xlarge)에서는 아직 실측하지 않았다.**

## 한 줄 결론

**합성 raw 기준, Spark 재집계는 30일 3.4배·90일 1.7배·270일 1.1배(pandas 대비 느림)로 격차가 줄다가
코어 8·6g에서 pandas와 동률(0.98배)이 된다. 정확성은 4개 완주 셀 전부 max_abs_err 0.0으로 일치한다.
다만 1000일(`--full` 2024~2026 전량 상당, 롱 2,800만 행)은 현재 잡이 3g·6g 모두 완주하지 못한다** —
3g는 `toPandas` 수집 중 힙 OOM, 6g는 기본 `spark.driver.maxResultSize`(1GiB) 초과다.

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

## 3. 해석

- **교차점**: 이 합성 기준에서 Spark는 어느 규모에서도 pandas를 확실히 앞서지 못했다. 270일(raw 1,800만 행)
  에서 격차가 1.1배로 닫히고 코어 8로 동률이다. `spark-compare-check`의 교차점(2,000만~5,000만 행)과
  같은 구간이다. 결과를 드라이버로 모으는 구조라 그 이후의 이점은 이 잡 형태로는 검증되지 않았다.
- **코어 확장**: local[3]->local[8]에서 52.2->45.7초(12%)로 작다. 서버는 4 vCPU라 8코어 설정을 쓸 수 없다.
- **서버(t3.xlarge 4 vCPU·16GB) 함의**: 서버 실측은 아직 없다. 로컬 22 논리코어 PC의 local[3] 수치를
  근거로 하면 일일 증분(`--years 2026`, 약 270일)은 약 1분 안팎이고 피크 RSS 6~8GB라 16GB 안에 들어오지만,
  AI 서빙·다른 배치와 겹치면 여유가 크지 않다. t3는 버스트 크레딧 CPU라 로컬보다 느릴 수 있다 —
  서버 측정(`server/` 스크립트가 따로 준비 중)으로 확인해야 한다.
- **판단**: 현 운영 규모에서 이 잡은 pandas보다 빠르지도 가볍지도 않다. 이 잡을 두는 이유는 속도가 아니라
  "raw 재집계가 pandas 롱과 같은 값을 낸다"는 독립 검증 경로(정확성 0.0 오차)다.

## 4. 한계

1. 합성 데이터다(값 분포·카디널리티·문자열 길이가 실데이터와 다름). 행수·스키마만 실 규모.
2. 셀당 1회 측정(반복·분산 없음). Windows 로컬이고 서버 t3.xlarge 실측 없음.
3. 270일 입력은 2025-12-31~2026-09-26이라 기본 `--years 2026` 입력과 정확히 같지 않다(전량 `--full` 셀).
4. 1000일 셀은 3g·6g 모두 실패했고 `maxResultSize` 상향 시도는 하지 않았다.
5. `results.jsonl`의 `spark_d1000`·`spark_d1000_m6g`는 `--force` 재실행으로 두 줄씩 있다(마지막 줄이 유효).
   첫 실행 줄의 `oom` 필드는 없고, 6g 줄의 `oom: false`는 실패 원인이 OOM이 아니라 maxResultSize라서다.

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
