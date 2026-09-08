# edge_time 정적 적재 처리량 — 행 단위 INSERT 대비 JDBC 배치

> 측정 규약은 `BE/docs/perf/README.md` (feat/INFRA-external-api-keys 브랜치, MR 병합 예정).

- 날짜 · 커밋: 2026-09-08 · `6b936b5` (feat/INFRA-subway-static-load)
- 환경: Windows 11 실습실 PC (Intel Core Ultra 9 185H 16C/22T, RAM 63.5 GB) · Docker Desktop 29.6.2 (22 CPU, 31 GB) · `postgres:16.15` 컨테이너 (같은 머신, 네트워크 지연 거의 없음) · JDK 21.0.11 · Spring Boot 4.1.1 `bootRun`
- 데이터 규모: `edge_time` **107,136행** (SUBWAY 엣지 744 × 요일 3 × 슬롯 48). 매 실행이 전체를 upsert 하며, 워밍업 이후에는 모두 "이미 있는 행 갱신" 경로다
- 반복: 모드별 워밍업 1회 + 측정 5회 (총 12회 연속 실행, 사이에 다른 부하 없음)

| 조건 | 스위치 | min | median | **p95** | max | 처리량(median) |
| --- | --- | --- | --- | --- | --- | --- |
| before: 행 단위 `JdbcTemplate.update` (statement 107,136회, autocommit) | `--load.write-mode=ROW` | 170,988 ms | 220,419 ms | 240,065 ms | 240,065 ms | 약 490 행/초 |
| after: `batchUpdate` 1,000행 묶음 (round trip 108회) | `--load.write-mode=BATCH` | 5,002 ms | 5,516 ms | 6,176 ms | 6,176 ms | 약 19,400 행/초 |

**median 기준 약 40배, p95 기준 약 39배 빠르다.** 절대값으로는 3분 40초가 5.5초가 된다.

명령:
```bash
# 저장소 루트. DB_URL·DB_USERNAME·DB_PASSWORD 환경변수 필요
bash .claude/perf/raw/run-edge-time-perf.sh   # 내부에서 ./gradlew bootRun --args="--load.write-mode=$mode" 를 12회 실행
```
원본: `.claude/perf/raw/2026-09-08-edge-time-load.csv` (mode,run,rows,ms,rows_per_sec,commit,ts), 스크립트 `.claude/perf/raw/run-edge-time-perf.sh` (Git 제외)

해석:
- 차이의 원인은 SQL이 아니라 **왕복 횟수**다. 두 모드는 같은 `INSERT ... ON CONFLICT DO UPDATE` 문을 쓰고, 배치는 1,000행마다 한 번 서버를 오간다.
- ROW 는 실행을 반복할수록 느려졌다(171초 → 240초). 같은 행을 계속 갱신하면 dead tuple 이 쌓여 autovacuum 전까지 갱신 비용이 오르는 것으로 보인다. BATCH 는 반대로 조금씩 빨라졌다(6.2초 → 5.0초, 캐시 warm).
- DB가 같은 머신의 도커라 네트워크 지연이 거의 없는 조건이다. EC2에서 원격 DB로 재측정하면 왕복 비용이 커져 ROW 쪽 격차가 더 벌어질 것으로 예상한다. **EC2 재측정 전까지 이 수치는 로컬 조건으로만 인용한다.**
- ROW 경로는 지우지 않고 `--load.write-mode=ROW` 스위치로 남겨 두어 언제든 같은 조건에서 재현할 수 있다.

다음 측정 후보: EC2 원격 DB 재측정, `COPY` 기반 적재와 비교(선택), 수집기 Redis 직접 쓰기 vs Kafka 경유 신선도 지연(2주차).
