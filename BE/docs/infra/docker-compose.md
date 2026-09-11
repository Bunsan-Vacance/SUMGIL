# Infra 변경 사항 (BE 초기 세팅)

## 왜 새 docker-compose.yml을 만들지 않았나

레포 루트에 이미 `Infra/docker/docker-compose.yml`(fe·be·db 골격, nginx 포함)이 있어서, 새로 만들면 파일이 중복된다. 그래서 이 파일에 `postgres`·`redis` 서비스를 **실제로 뜨는 상태**로 추가했다.

## 추가된 서비스

```yaml
postgres:
  image: postgres:16
  container_name: sumgil-postgres
  environment:
    POSTGRES_DB: sumgil
    POSTGRES_USER: sumgil
    POSTGRES_PASSWORD: sumgil1234
  ports:
    - "5432:5432"
  volumes:
    - sumgil_postgres_data:/var/lib/postgresql/data

redis:
  image: redis:7
  container_name: sumgil-redis
  ports:
    - "6379:6379"
  volumes:
    - sumgil_redis_data:/data
```

### `kafka` (S15P21A104-74, 2026-09-11 추가)

수집기 → 컨슈머 사이의 버퍼. `apache/kafka:4.2.1` 단일 노드(KRaft — 4.x 에는 ZooKeeper 가 없다).
리스너를 둘로 나눈다: 컨테이너끼리 `kafka:19092`(미공개), 호스트에서 `localhost:9092`.
구성값의 의미·검증 절차·함정은 [kafka.md](kafka.md)에 따로 정리했다.

```bash
docker compose -f Infra/docker/docker-compose.yml up -d --wait kafka
```

`fe`, `be` 전체 스택 블록은 각 파트 Dockerfile이 없어 그대로 주석 처리해뒀다 (`Infra/README.md` 진행 순서 1~2번 참고). `db`라는 이름의 임시 플레이스홀더 서비스는 `postgres`로 대체했다 — BE 쪽 `.claude/skills/verify`와 이름을 맞추기 위함.

## 사용법

```bash
# 기동
docker compose -f Infra/docker/docker-compose.yml up -d postgres redis

# 종료
docker compose -f Infra/docker/docker-compose.yml down
```

## 확인된 이슈

로컬 검증 중 Docker Desktop이 꺼져 있어 `docker compose up`이 다음 에러로 실패했다:

```
unable to get image 'redis:7': failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
```

Docker Desktop을 실행한 뒤 다시 시도하면 된다. 이번 작업에서는 이 문제로 `postgres`/`redis`를 띄운 상태에서의 `./gradlew build` 전체 통과까지는 확인하지 못했고, `compileJava`/`compileTestJava`/`bootJar`까지만 로컬에서 검증했다.
