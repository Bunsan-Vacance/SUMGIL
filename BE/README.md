# Backend

**스택** Java 21 · Spring Boot 4.1 · Gradle · PostgreSQL · Redis

> **숨길** — 지하철 탈출 내비게이션.
> AI 파트가 배치로 만들어둔 산출물과 실시간 스트림 결과를 **사용자 요청 시점에 조합해 두 선택지로 내려주는 파트**다.

---

## 1. 이 파트가 하는 것

핵심은 **"지금 내려도 돼?"** 요청 하나를 받아 A안·B안을 계산해 돌려주는 것이다.

```
클라이언트 ── "한티역, 목적지 역삼" ──▶ [BE]
                                        ├─ 역전 테이블 조회 (사전계산, Redis)
                                        ├─ 실시간 재고 조회 (Redis, 스트림 갱신)
                                        ├─ 실시간 도착정보 조회
                                        └─ 슬라이더 가중치 반영해 경로 점수 재계산
                                             ▼
                              A안 14분 / B안 10분 · 잔여 7대 · 착석 8%
```

무거운 계산은 전부 AI 파트의 야간 배치가 끝내둔다. BE는 **조회 + 실시간 보정 + 사용자 취향 반영**을 맡는다. 요청마다 다익스트라를 처음부터 돌리지 않는다.

## 2. API 초안

> 엔드포인트·필드명은 확정 전 초안이다. FE와 함께 확정하고 Swagger로 명세를 고정한다.

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/v1/stations` | 역 검색·자동완성 |
| `POST` | `/api/v1/routes` | 목적지 입력 → 기준 경로 안내 |
| `POST` | `/api/v1/escape` | **킬러 기능.** 현재 역 기준 A안/B안 비교 |
| `GET` | `/api/v1/stations/{id}/seat-chance` | 착석 기회 지수 + 자리 회전 예측 |
| `GET` | `/api/v1/bike-stations/nearby` | 역 인근 대여소 + 실시간 잔여 대수 |
| `GET` | `/api/v1/health` | 헬스 체크 (Actuator) |

**`POST /api/v1/escape` 응답 형태 (초안)**

```json
{
  "subway": {
    "totalMinutes": 15,
    "breakdown": { "ride": 4, "transferWalk": 3, "transferWait": 4, "exitWalk": 2 },
    "congestionRate": 148,
    "seatChanceIndex": 7,
    "seatChanceAfter": { "station": "선릉", "stopsAhead": 3, "index": 55 }
  },
  "bike": {
    "totalMinutes": 13,
    "breakdown": { "walkToDock": 2, "rentProcess": 1, "ride": 7.4, "returnWalk": 2 },
    "source": "OBSERVED_MEDIAN",
    "dock": { "name": "한티역 2번출구", "available": 6, "predictedOnArrival": 4 }
  },
  "verdict": "BIKE_FASTER",
  "blockedReason": null
}
```

- `source` — 실측 이력(`OBSERVED_MEDIAN`)인지 OSRM 추정(`ROUTED_ESTIMATE`)인지 구분해 내려준다. 근거의 신뢰도를 클라이언트가 표시할 수 있어야 한다.
- `blockedReason` — 재고 부족·우천 등으로 자전거를 추천하지 않는 경우 사유를 담는다.

## 3. 경로 엔진

역·정류장·대여소를 노드로 하는 그래프에서 다익스트라를 응용한다.

```
구간 점수 = 소요시간 + λ × 혼잡 페널티
```

**λ가 곧 "빠름 ↔ 쾌적함" 슬라이더**다. 사용자가 슬라이더를 옮기면 λ가 바뀌고 경로가 다시 뽑힌다. λ의 기본값은 AI 파트가 사용자 행동 로그로 캘리브레이션한 값을 쓴다 — 감으로 정한 상수가 아니다.

## 4. 데이터 흐름

```
[AI 배치 산출물]  역전 테이블 · 착석 지수 · 소요시간표
        │
        ├──▶ PostgreSQL   정적·준정적 데이터 (역, 대여소, 사전계산 결과)
        │
[Spark Streaming]  실시간 재고 · 도착정보
        │
        └──▶ Redis        TTL 짧은 실시간 값
                 │
              [BE 조회] ──▶ 응답 조합
```

- **Redis가 죽으면 실시간 재고를 못 읽는다.** 이 경우 자전거 추천을 차단하고 `blockedReason`으로 사유를 내려준다 — 틀린 재고로 헛걸음을 만들지 않는다.
- 사전계산 결과가 없는 구간(범위 밖 노선)은 A안만 응답하고 B안은 `null`로 둔다.

## 5. 사전 요구사항

| 항목 | 버전 | 상태 |
| --- | --- | --- |
| JDK | 17 또는 21 | ✅ 설치됨 (OpenJDK 21.0.12 LTS) |
| Gradle | — | Wrapper 사용, 별도 설치 불필요 |
| Docker | — | ✅ 설치됨 (로컬 DB·Redis 구동용) |

## 6. 초기화

프로젝트 생성 완료 (Initializr, 설정은 아래 표와 같다).
추가 의존성: Flyway, springdoc-openapi, logstash 인코더, dotenv(로컬 전용).

| 항목 | 값 |
| --- | --- |
| Project | Gradle - Groovy |
| Language | Java |
| Spring Boot | 3.x (최신 안정 버전) |
| Packaging | Jar |
| Java | 21 |
| Group | `com.ssafy` |
| Artifact | `s15p21a104` |

**의존성** — Spring Web · Spring Data JPA · Spring Data Redis · PostgreSQL Driver · Lombok · Validation · Actuator · DevTools

```bash
cd BE
curl -G https://start.spring.io/starter.zip \
  -d type=gradle-project -d language=java -d javaVersion=21 \
  -d groupId=com.ssafy -d artifactId=s15p21a104 -d name=s15p21a104 \
  -d dependencies=web,data-jpa,data-redis,postgresql,lombok,validation,actuator,devtools \
  -o starter.zip
unzip starter.zip && rm starter.zip
```

생성 후 `springdoc-openapi-starter-webmvc-ui`를 추가해 Swagger를 붙인다.

> 스캐폴딩 도구가 디렉터리 구조를 직접 만들기 때문에, 충돌을 피하려고 하위 폴더를 미리 만들어두지 않았다.

## 7. 목표 패키지 구조

```
BE/src/main/java/com/ssafy/s15p21a104/
├─ api/           인터페이스(*Api) + 구현(*Controller), 도메인별 하위 패키지
├─ domain/
│  ├─ station/     역·노선·환승 정보
│  ├─ bus/         정류소·버스노선
│  ├─ bike/        대여소·재고 예측
│  ├─ congestion/  혼잡도
│  └─ route/       경로 그래프 (엣지)
├─ global/
│  ├─ config/      필터·Swagger·JPA·Flyway·Redis·CORS(미사용)
│  ├─ exception/   전역 예외 처리
│  ├─ response/    공통 응답 래퍼
│  ├─ cache/       Redis 키 네이밍·TTL 정책
│  └─ common/      감사 기반 엔티티
└─ infrastructure/ 외부 연동 (향후)
```

도메인 단위로 수직 분할한다. 레이어를 최상위에 두면 도메인이 늘어날수록 탐색이 어려워진다.

## 8. 실행

```bash
# DB·Redis 기동 (저장소 루트에서)
docker compose -f Infra/docker/docker-compose.yml up -d postgres redis

# BE 실행 (BE 디렉토리에서, local 프로파일 필수)
cd BE
SPRING_PROFILES_ACTIVE=local ./gradlew bootRun    # 개발 서버 (http://localhost:8080)
./gradlew build      # 빌드
./gradlew test       # 테스트
```

로컬 접속 정보는 `application-local.yml`(Git 제외)에 둔다.
`BE/.env.example`에 키 목록이 있다.

## 9. 작업 규칙

- **DB 접속 정보·API 키는 `application.yml`에 직접 쓰지 않는다.** 환경 변수 또는 `application-local.yml`(Git 제외)로 분리하고, `application.yml`에는 키 이름만 남긴다.
- Entity를 Controller 응답으로 그대로 내보내지 않는다. DTO로 변환한다.
- API 명세는 Swagger(springdoc-openapi)로 자동 생성하고 FE 타입 정의와 1:1로 맞춘다.
- **외부 API를 BE가 직접 폴링하지 않는다.** 실시간 수집은 스트림 파이프라인이 맡고 BE는 Redis만 읽는다. 호출 한도(`bikeList` 1,000건/호출 등)를 여러 곳에서 소모하면 관리가 불가능해진다.

## 10. 다음 할 일

1. ~~Spring Initializr로 프로젝트 생성, Swagger 연결~~ — 완료
2. **`POST /api/v1/escape` 응답 스키마를 FE와 확정** — 나머지는 여기서 파생된다
3. ~~로컬 PostgreSQL·Redis를 Docker Compose로 띄우기~~ — 완료. `Infra/docker/docker-compose.yml`
