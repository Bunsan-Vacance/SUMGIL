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

2. `local` 프로필로 애플리케이션 실행:

   ```bash
   cd BE
   SPRING_PROFILES_ACTIVE=local ./gradlew bootRun
   ```

   (또는 IDE 실행 설정에 `SPRING_PROFILES_ACTIVE=local` 환경변수 추가)

3. 프로필 없이(`DB_URL`/`DB_USERNAME`/`DB_PASSWORD` 환경변수를 직접 넣는 방식)도 실행 가능 — 배포 환경은 이 방식을 쓴다.

## 현재 상태 / 다음 할 일

- `spring.jpa.hibernate.ddl-auto: update`는 개발 편의용이다. 엔티티가 생기고 팀 스키마가 안정되면 Flyway/Liquibase 같은 마이그레이션 도구로 바꾸는 걸 고려한다.
- 아직 JPA 엔티티가 하나도 없다 — 이번 작업은 커넥션 설정까지만이고, 스키마는 비어 있다.
- 로컬 검증 시 Docker Desktop이 꺼져 있으면 `docker compose up`이 `dockerDesktopLinuxEngine` 관련 에러로 실패한다. Docker Desktop을 먼저 켜야 한다.
