# BE CI (`be-test`)

`S15P11A108`의 `be-test` job을 참고해서 이 프로젝트 스택에 맞춰 작성했다. 루트 `.gitlab-ci.yml`에 있다.

## 언제 도나

`BE/**/*`가 바뀐 커밋에서만 실행된다 (`rules.changes`).

## 뭘 하나

1. `eclipse-temurin:21-jdk-jammy` 이미지에서 실행.
2. GitLab CI `services`로 `postgres:16`, `redis:7` 컨테이너를 붙인다 — `Infra/docker/docker-compose.yml`과 같은 버전.
3. `application.yml`이 요구하는 `DB_URL`/`DB_USERNAME`/`DB_PASSWORD`/`REDIS_HOST`/`REDIS_PORT`를 서비스 컨테이너 정보로 `export`한다 (로컬의 `application-local.yml`과 달리 CI는 프로필 대신 환경변수를 직접 준다).
4. TCP 연결 확인(`/dev/tcp/...`)으로 서비스가 붙는지 먼저 확인한 뒤 `./gradlew build`.

## 로컬에서 이 방식 그대로 검증한 이력

`local` 프로필이 아니라 CI와 동일하게 `DB_URL`/`DB_USERNAME`/`DB_PASSWORD`/`REDIS_HOST`/`REDIS_PORT`만 export한 상태로 `./gradlew test --rerun`을 실제 postgres/redis 컨테이너에 대해 돌려서 통과 확인했다 (2026-09-07).

## 알아둘 것

- **러너 tag(`CI`) 필수.** 이 레포에 "ai job에 tags 안 넣어서 pending 무한 대기"였던 이력(`S15P21A104-34`)이 있어서, `be-test`에도 처음부터 `tags: [CI]`를 넣어뒀다.
- `alias`를 이미지 이름(`postgres`/`redis`)과 같게 두면 러너가 자동 생성하는 별칭과 충돌해서 조용히 skip되고 DB 연결이 실패한다 — `db`/`cache`처럼 겹치지 않는 이름을 쓴다.
- 이건 **테스트(CI)만** 이다. 배포(CD)는 아직 없다 — `Dockerfile`도, EC2도, `deploy` job도 없는 상태. `docs/README.md` 6절 참고.
