# edge_time 정적 적재 처리량 재측정 — 193,536행, 행 단위 INSERT 대비 JDBC 배치

> `2026-09-08-edge-time-load.md`(107,136행)의 후속. 70·111·113 적재로 행이 1.8배 늘어난 뒤 같은 스위치·같은 반복 규약으로 다시 잰 것. `load-subway.md` "남은 일"에 있던 "12회 재측정" 항목을 이 파일로 닫는다.

- 날짜 · 커밋: 2026-09-11 · `ebdbd54` (develop-BE 계열, Kafka PoC 커밋 시점)
- 환경: Windows 11 실습실 PC (Intel Core Ultra 9 185H 16C/22T, RAM 63.5 GB) · Docker Desktop 29.6 · `postgres:16` 컨테이너 (compose 태그. 09-08 기록 시점 이미지는 16.15, 그 사이 재pull 없음) · JDK 21 · Spring Boot 4.1.1 `bootRun --offline`
- 데이터 규모: `edge_time` **193,536행** (엣지 1,344 × 요일 3 × 슬롯 48 — 시각표 1~9호선 936 + KTDB 링크 9노선 408). 매 실행이 `--load.sources=subway` 전체(line·station·transfer·edge_time·prune)를 돌리고, 표의 시간은 그중 `적재 edge_time` 로그 한 줄의 값이다. 워밍업 이후에는 전부 "이미 있는 행 갱신" 경로
- 반복: 모드별 워밍업 1회 + 측정 5회 (총 12회 연속, 사이에 다른 부하 없음). **n=5라 p95는 최댓값과 같다** (09-08과 같은 조건)

| 조건 | 스위치 | min | median | **p95** | max | 처리량(median) |
| --- | --- | --- | --- | --- | --- | --- |
| before: 행 단위 `JdbcTemplate.update` (statement 193,536회) | `--load.write-mode=ROW` | 244,043 ms | 250,238 ms | 285,428 ms | 285,428 ms | 약 770 행/초 |
| after: `batchUpdate` 1,000행 묶음 (round trip 194회) | `--load.write-mode=BATCH` | 3,350 ms | 3,482 ms | 3,611 ms | 3,611 ms | 약 55,600 행/초 |

**median 기준 약 72배, p95 기준 약 79배 빠르다.** 절대값으로는 4분 10초가 3.5초가 된다. 09-08(107,136행)의 40배보다 격차가 커졌다 — 행이 늘수록 왕복 횟수 차이가 그대로 시간 차이로 쌓이기 때문이다.

명령:
```bash
# 저장소 루트. 컨테이너 sumgil-postgres·sumgil-redis 기동 상태. 스크립트 안에서 DB_URL 등 env 를 export 한다
bash .claude/perf/raw/run-edge-time-perf-2026-09-11.sh
# 내부: ./gradlew bootRun --offline --args="--load.write-mode=$mode --load.sources=subway" 를 BATCH 6회 → ROW 6회
```
원본: `.claude/perf/raw/2026-09-11-edge-time-load.csv` (mode,run,rows,ms,rows_per_sec,commit,ts), 스크립트 `.claude/perf/raw/run-edge-time-perf-2026-09-11.sh` (Git 제외)

해석:
- 차이의 원인은 09-08과 같다. 두 모드는 같은 `INSERT ... ON CONFLICT DO UPDATE` 문을 쓰고, 배치는 1,000행마다 한 번 서버를 오간다(`UpsertWriter.BATCH_SIZE = 1000`, 두 측정 사이 변경 없음).
- **09-08 수치와 나란히 놓고 "개선"이라 부르지 않는다.** 행당 처리량이 BATCH 19,400 → 55,600 행/초, ROW 490 → 770 행/초로 **두 모드가 함께** 빨라졌는데, 두 측정 사이에 로더 커밋이 16개(70·103·111·113·114·73) 있어 행 구성·UPSERT 대상·DB 상태가 전부 달라졌다. 같은 커밋에서 두 규모를 재측정하지 않았으므로 원인을 분리할 수 없다. 두 모드가 같이 움직인 것으로 보아 배치 로직이 아니라 공통 경로 쪽 변화일 가능성이 크지만, 이것은 추정이다.
- **09-08 해석 중 "ROW는 반복할수록 느려진다(dead tuple)"는 이번 데이터가 지지하지 않는다.** 이번 ROW는 반대로 285 → 270 → 250 → 244 → 245초로 빨라졌다. 아래 부록의 dead tuple 실험도 같은 방향이다. 09-08 파일은 고치지 않고 여기서 바로잡는다 — 09-08의 ROW 감속 원인은 미확인이다.
- DB가 같은 머신의 도커라 네트워크 지연이 거의 없는 조건이다. **EC2 재측정 전까지 이 수치는 로컬 조건으로만 인용한다.** 09-14 prod 적재(`load-prod.md`)의 edge_time 약 13,300 행/초는 SSH 터널 경유 1회 측정치라 이 표와 비교 대상이 아니다.

## 부록 — dead tuple 누적과 BATCH 처리량 (같은 날, 10회 연속)

09-08의 "dead tuple 때문에 느려진다" 가설을 직접 보려고 BATCH 모드를 10회 연속 돌리며 매 실행 뒤 `edge_time`의 dead tuple 수와 테이블·인덱스 크기를 함께 적었다.

| 실행 | ms | 행/초 | dead tuple | 테이블 MB | 인덱스 MB |
| --- | --- | --- | --- | --- | --- |
| 1 | 4,131 | 46,849 | 84,185 | 22.2 | 13.7 |
| 2 | 3,905 | 49,561 | 146,698 | 26.8 | 14.6 |
| 3 | 3,787 | 51,105 | 197,131 | 30.3 | 14.8 |
| 4 | 3,687 | 52,491 | 235,711 | 32.7 | 14.9 |
| 5 | 3,656 | 52,936 | 265,162 | 34.5 | 14.9 |
| 6 | 3,600 | 53,760 | 284,596 | 35.7 | 14.9 |
| 7 | 3,568 | 54,242 | 298,460 | 36.4 | 14.9 |
| 8 | 3,529 | 54,841 | 306,655 | 36.9 | 14.9 |
| 9 | 3,580 | 54,060 | 312,934 | 37.2 | 14.9 |
| 10 | 3,467 | 55,822 | 316,257 | 37.4 | 14.9 |

- dead tuple이 3.8배(84k → 316k), 테이블이 68%(22 → 37 MB) 불어나는 동안 **처리량은 오히려 4,131 → 3,467 ms로 좋아졌다.** 이 규모에서는 dead tuple 누적이 upsert 시간을 지배하지 않는다.
- 10회 동안 갱신한 행은 누적 약 194만인데 dead tuple은 32만에서 늘어나는 속도가 둔해졌다. 중간에 autovacuum이 돌았다고 보이지만 vacuum 로그는 남기지 않았다(추정).
- 1회차 4,131 ms가 위 표의 BATCH median(3,482 ms)보다 느린 것은 이 실험을 별도 세션에서 콜드 상태로 시작했기 때문으로 보인다. 워밍업 없이 1회차부터 적었다.
- 한계: CSV에 커밋·시각 열이 없다(같은 날 측정, 커밋은 위와 같은 `ebdbd54`로 기억하나 기록으로 확정하지 못함). dead tuple·크기 조회 SQL(`pg_stat_user_tables.n_dead_tup`, `pg_relation_size`·`pg_indexes_size`)은 저장하지 않았다. 재현하려면 실행 사이에 그 두 조회를 끼워 넣는 스크립트를 다시 써야 한다.

원본: `.claude/perf/raw/2026-09-11-bloat-experiment.csv` (run,ms,rows_per_sec,dead_tup,table_mb,index_mb)

다음 측정 후보: EC2 원격 DB 재측정(prod Postgres, 터널 없이 클러스터 안에서), `COPY` 기반 적재와 비교(선택), 같은 커밋에서 107k·193k 두 규모 재측정(행당 처리량 변화의 원인 분리).
