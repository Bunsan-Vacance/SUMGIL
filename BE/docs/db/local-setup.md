# DB / Redis 로컬 설정

## 설정 분리 이유

루트 `CLAUDE.md`, `BE/README.md` 9절 규칙: **DB 접속 정보를 `application.yml`에 직접 쓰지 않는다.** 그래서 두 파일로 나눴다.

| 파일 | 내용 | Git |
| --- | --- | --- |
| `src/main/resources/application.yml` | 환경변수 참조만 (`${DB_URL}` 등) | 커밋됨 |
| `src/main/resources/application-local.yml` | 실제 로컬 접속 정보 (docker-compose 기본값과 동일) | `.gitignore`로 제외 |

## 로컬 실행 방법

1. Postgres·Redis 컨테이너 기동 (레포 루트에서):

   ```bash
   docker compose -f Infra/docker/docker-compose.yml up -d postgres redis
   ```

2. **처음 클론했거나 데이터가 비어 있으면, 정적 데이터 적재를 한 번 돌린다.** 각자 로컬 DB는 공유되지 않으므로
   (시드 DB 없음) 이 단계 없이 3번만 실행하면 테이블은 있어도 비어 있어서 모든 조회가 빈 결과 또는 에러가 된다.

   ```bash
   cd BE
   SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun
   ```

   지하철(역·노선·환승·구간 소요시간)·버스·따릉이·KTDB geometry를 한 번에 채운다. API 서버는 안 뜨고 적재만 하고 종료된다.
   프로파일 옵션(`--load.sources`, `--load.dry-run` 등)과 원천·검증 규칙은 [`load-subway.md`](load-subway.md), [`load-bus-bike.md`](load-bus-bike.md)를 참고한다.
   멱등하니 몇 번을 다시 돌려도 안전하다 — 팀원이 로더 코드나 원천 데이터를 바꿔 merge했을 때 다시 실행해서 최신 상태로 맞추면 된다.

3. `local` 프로필로 애플리케이션(API 서버) 실행:

   ```bash
   SPRING_PROFILES_ACTIVE=local ./gradlew bootRun
   ```

   (또는 IDE 실행 설정에 `SPRING_PROFILES_ACTIVE=local` 환경변수 추가)

4. 프로필 없이(`DB_URL`/`DB_USERNAME`/`DB_PASSWORD` 환경변수를 직접 넣는 방식)도 실행 가능 — 배포 환경은 이 방식을 쓴다.

## 현재 상태

- 스키마는 Flyway 마이그레이션(`src/main/resources/db/migration/`)으로 관리한다(`spring.jpa.hibernate.ddl-auto: validate`).
- 데이터는 위 2번의 정적 적재 파이프라인(`com.ssafy.s15p21a104.load`)이 채운다 — CSV/공공데이터 원천을 파싱해 검증 후 upsert. 자세한 테이블별 결과·원천은 `load-subway.md`/`load-bus-bike.md` 참고.
- 로컬 검증 시 Docker Desktop이 꺼져 있으면 `docker compose up`이 `dockerDesktopLinuxEngine` 관련 에러로 실패한다. Docker Desktop을 먼저 켜야 한다.
