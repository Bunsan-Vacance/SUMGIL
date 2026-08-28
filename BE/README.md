# Backend

**스택** Java · Spring Boot · Gradle

분석 결과 조회 API와 서비스 로직을 담당한다.

---

## 사전 요구사항

| 항목 | 버전 | 상태 |
| --- | --- | --- |
| JDK | 17 또는 21 | ✅ 설치됨 (OpenJDK 21.0.12 LTS) |
| Gradle | — | Wrapper 사용, 별도 설치 불필요 |

## 초기화

**아직 프로젝트가 생성되지 않았다.** 폴더만 잡아둔 상태이며, [Spring Initializr](https://start.spring.io)에서 아래 설정으로 생성해 이 디렉터리에 푼다.

| 항목 | 값 |
| --- | --- |
| Project | Gradle - Groovy |
| Language | Java |
| Spring Boot | 3.x (최신 안정 버전) |
| Packaging | Jar |
| Java | 21 |
| Group | `com.ssafy` |
| Artifact | `s15p21a104` |

**의존성**

- Spring Web
- Spring Data JPA
- PostgreSQL Driver
- Lombok
- Spring Boot DevTools
- Validation
- Spring Boot Actuator

CLI로 생성하려면 아래처럼 받는다.

```bash
cd BE
curl -G https://start.spring.io/starter.zip \
  -d type=gradle-project -d language=java -d javaVersion=21 \
  -d groupId=com.ssafy -d artifactId=s15p21a104 -d name=s15p21a104 \
  -d dependencies=web,data-jpa,postgresql,lombok,devtools,validation,actuator \
  -o starter.zip
unzip starter.zip && rm starter.zip
```

> 스캐폴딩 도구가 디렉터리 구조를 직접 만들기 때문에, 충돌을 피하려고 하위 폴더를 미리 만들어두지 않았다.

## 목표 패키지 구조

```
BE/src/main/java/com/ssafy/s15p21a104/
├─ global/
│  ├─ config/      설정 (CORS, Swagger, JPA)
│  ├─ exception/   전역 예외 처리
│  └─ common/      공통 응답 포맷, 유틸
└─ domain/
   └─ {도메인}/
      ├─ controller/
      ├─ service/
      ├─ repository/
      ├─ entity/
      └─ dto/
```

도메인 단위로 수직 분할한다. 레이어를 최상위에 두면 도메인이 늘어날수록 탐색이 어려워진다.

## 실행

```bash
./gradlew bootRun    # 개발 서버 (http://localhost:8080)
./gradlew build      # 빌드
./gradlew test       # 테스트
```

## 작업 규칙

- **DB 접속 정보·API 키는 `application.yml`에 직접 쓰지 않는다.** 환경 변수 또는 `application-local.yml`(Git 제외)로 분리하고, `application.yml`에는 키 이름만 남긴다.
- Entity를 Controller 응답으로 그대로 내보내지 않는다. DTO로 변환한다.
- API 명세는 Swagger(springdoc-openapi)로 자동 생성하고, 프론트엔드 타입 정의와 맞춘다.
