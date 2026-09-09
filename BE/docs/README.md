# BE 초기 세팅 정리 (S15P21A104-60)

`feat/S15P21A104-60-backend-init` 브랜치에서 진행한 백엔드 초기 세팅 내용 정리. Spring Boot 프로젝트 자체가 없던 상태에서 시작해서, 프로젝트 생성 + mock API 2개 + 로컬 DB/Redis 연결 설정까지 끝냈고, 실제 Postgres/Redis 컨테이너로 연결까지 검증했다. **EC2 배포 준비는 아직 안 됐다** (6절 참고).

## 1. 뭘 만들었나

Spring Initializr로 프로젝트를 생성했다.

| 항목 | 값 |
| --- | --- |
| Group / Artifact | `com.ssafy` / `s15p21a104` |
| 베이스 패키지 | `com.ssafy.s15p21a104` |
| Java | 21 |
| Spring Boot | 4.1.1 |
| 빌드 도구 | Gradle (Wrapper 포함, 별도 설치 불필요) |

## 2. 파일 구조

```
BE/
├─ build.gradle, settings.gradle, gradlew(.bat), gradle/   ← Initializr 생성
├─ src/main/java/com/ssafy/s15p21a104/
│  ├─ S15p21a104Application.java   ← @SpringBootApplication
│  ├─ controller/
│  │  ├─ RouteController.java      ← GET /api/routes/search
│  │  └─ StationController.java    ← GET /api/stations/nearby
│  └─ dto/
│     ├─ RouteSearchResponse.java
│     └─ StationResponse.java
├─ src/main/resources/
│  ├─ application.yml         ← 커밋됨. 환경변수 참조만 있음 (비밀번호 없음)
│  ├─ application-local.yml   ← Git 제외. 로컬 실제 접속 정보
│  ├─ application-load.yml    ← 정적 적재 프로파일 (local,load 로 실행)
│  ├─ db/migration/           ← Flyway V1 스키마, V2 source 열 확대
│  ├─ data/subway/            ← 지하철 정적 적재 원천 CSV·설정 (출처는 그 폴더 README)
│  ├─ data/bus/               ← 버스 정류소·노선 원천 CSV (OA-15067 · OA-1095)
│  └─ data/bike/              ← 따릉이 대여소 스냅샷(bikeList)·파일(OA-13252)
├─ src/main/java/.../load/    ← 정적 적재 로더 (load 프로파일, docs/db/load-subway.md · load-bus-bike.md)
├─ docs/                      ← 이 폴더. api/db/global/infra/external/perf 로 나눠서 정리
│                                (external: 외부 데이터 소스 조사·샘플, perf: 성능 측정 기록)
├─ scripts/external/          ← 외부 API 1회 호출 probe (node, 의존성 없음)
├─ scripts/data/              ← 원천 변환: xlsx→CSV, bikeList 스냅샷 (node, 의존성 없음)
└─ .claude/                   ← Git 제외 (Claude Code 로컬 설정, 팀 공유 안 됨)
```

**주의**: `controller/`, `dto/`가 패키지 최상위에 바로 있는 평평한 구조다. `BE/README.md` 7절이 정의한 목표 구조는 `domain.<도메인명>.controller` 식으로 도메인 단위 분할인데, 이번 작업은 지시문에 있던 mock 명세를 그대로 옮긴 거라 그 구조를 아직 안 따른다. 실제 도메인(station/escape/congestion/bike/route) 로직을 붙이기 시작할 때 옮겨야 한다 — 자세한 건 `.claude/skills/scaffold`(로컬에만 있음, Git 제외) 참고.

## 3. 로컬에서 돌려보는 법

```bash
# 1) 레포 루트에서 postgres·redis 기동 (Docker Desktop 켜져 있어야 함)
docker compose -f Infra/docker/docker-compose.yml up -d postgres redis

# 2) BE 폴더에서 local 프로필로 실행
cd BE
SPRING_PROFILES_ACTIVE=local ./gradlew bootRun
```

`http://localhost:8080/api/routes/search?origin=한티역&destination=역삼`, `http://localhost:8080/api/stations/nearby?lat=37.5&lng=127.0`로 확인 가능.

## 4. 왜 지시문과 다르게 한 부분이 있나

- **DB 접속 정보를 `application.yml`에 안 넣음** — 루트 `CLAUDE.md`/`BE/README.md` 9절 규칙 때문. `application-local.yml`(Git 제외)로 분리. 자세한 건 [db/local-setup.md](./db/local-setup.md).
- **docker-compose를 새로 안 만들고 기존 파일에 추가** — `Infra/docker/docker-compose.yml`이 이미 있어서 중복 방지. 자세한 건 [infra/docker-compose.md](./infra/docker-compose.md).

## 5. 팀이 확인/결정해야 할 것

1. **API 명세 불일치** — 지금 만든 `GET /api/routes/search`, `GET /api/stations/nearby`는 `BE/README.md` 2절에 이미 있던 API 초안(`/api/v1/escape` 등, `/api/v1/` 버전 프리픽스, 다른 응답 구조)과 형태가 다르다. FE 연동 전에 어느 쪽으로 갈지 정해야 한다. 자세한 건 [api/mock-endpoints.md](./api/mock-endpoints.md).
2. **패키지 구조 전환 시점** — 지금의 평평한 `controller/`, `dto/`를 언제 도메인 단위(`domain.route`, `domain.station` ...)로 옮길지.
3. **EC2 배포(CD)는 아직 준비 안 됨** — CI(테스트)는 생겼지만 배포는 별개다. `BE/Dockerfile`이 없고, `Infra/docker/docker-compose.yml`의 `fe`/`be` 블록도 주석 처리 상태다. 환경변수를 `.env`/`.env.example`로 분리하는 작업(`Infra/README.md` 3번 항목)도 안 됐다. EC2에 올리려면 이것들부터 해야 한다.

## 6. CI

`BE/**/*` 변경 시 도는 `be-test` job을 루트 `.gitlab-ci.yml`에 추가했다 (`S15P11A108`의 be-test 참고, postgres:16/redis:7로 이 프로젝트 스택에 맞춤). 자세한 건 [infra/ci.md](./infra/ci.md).

## 7. 검증 이력

- `docker compose -f Infra/docker/docker-compose.yml up -d postgres redis`로 컨테이너 기동 확인 (정상)
- `SPRING_PROFILES_ACTIVE=local ./gradlew build` → **`BUILD SUCCESSFUL`** (JPA/Redis 연결 포함한 `contextLoads()` 테스트까지 통과)
- CI와 동일하게 `local` 프로필 없이 `DB_URL`/`DB_USERNAME`/`DB_PASSWORD`/`REDIS_HOST`/`REDIS_PORT`만 export한 상태로 `./gradlew test --rerun`도 통과 확인 — `be-test` job이 실제로 성공할 조합임을 로컬에서 미리 검증한 것.
- 단, `./gradlew bootRun`으로 실제 서버를 띄워 API를 직접 호출해보는 것까지는 아직 안 했다.
- 검증 후 컨테이너는 다시 내려뒀다 (`docker compose ... down`).

## 8. 커밋 상태

아래 커밋들로 나눠서 로컬에 반영했고, **아직 push 전**이다.

```
[S15P21A104-60] chore: Spring Boot 프로젝트 초기화 및 mock 라우트/대여소 API 추가
[S15P21A104-60] chore: 로컬 개발용 Postgres·Redis 서비스 추가
[S15P21A104-60] docs: BE 초기 세팅 요약 문서 추가
[S15P21A104-60] chore: BE 빌드/테스트 CI job(be-test) 추가
```
