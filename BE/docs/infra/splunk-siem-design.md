# 로컬 Splunk 연동 설계 (개인 데모용 — 보안 직무 포트폴리오)

> 팀 공유 기능이 아니라 **개인 로컬 환경에서만 도는 데모**다. 상시 운영 인프라(EC2 k3s)는 건드리지 않는다.

## 목적

"보안 이벤트·로그 데이터 수집·분석, 이상징후 기반 위협 선탐지" 경험을 실제로 보여주기 위해, BE가 이미 내고 있는 구조화 JSON 로그를 로컬 Splunk로 흘려보내고 그 위에서 이상 탐지 검색·대시보드를 만든다.

## 전체 그림

```
BE(Spring Boot, local 프로필)
   │  Logback 신규 appender(SPLUNK_HEC)
   │  HTTP POST (HEC 토큰)
   ▼
로컬 Splunk Enterprise(Free 티어)
   │  HEC input → index(sumgil)
   ▼
Splunk 검색·대시보드·(스케줄) 알림
```

- BE 프로세스와 Splunk 둘 다 사용자 로컬 머신에서만 돈다. 기존 EC2 k3s 배포·상시 운영 로그 파이프라인과는 완전히 분리된 별도 경로다.
- 기존 `logback-spring.xml`의 `CONSOLE_TEXT`/`FILE_JSON` appender는 그대로 둔다 — 새 appender를 **추가**만 한다.

## 1. Splunk 쪽 준비 (사용자가 직접, 설계만이라 실행은 안 함)

1. Splunk Enterprise Free 설치(로컬).
2. Settings → Data Inputs → HTTP Event Collector에서 토큰 발급, 인덱스 `sumgil` 지정.
3. Free 티어 제약: 일 500MB 인덱싱 상한, **스케줄 알림(실시간 알럿)은 Free 티어에 없음** — 로그 양이 이 데모 규모에선 문제 안 되지만, "자동 알림"을 데모하려면 수동 저장 검색(saved search)을 주기적으로 직접 돌리는 식으로 보여줘야 한다는 제약을 감안한다.

## 2. BE 쪽 추가 (Logback appender)

### 의존성

`splunk-library-javalogging`(Splunk 공식 Java 로깅 라이브러리, `HttpEventCollectorLogbackAppender` 제공) 추가.

### 새 appender

```xml
<appender name="SPLUNK_HEC" class="com.splunk.logging.HttpEventCollectorLogbackAppender">
    <url>${SPLUNK_HEC_URL:-http://localhost:8088}</url>
    <token>${SPLUNK_HEC_TOKEN:-}</token>
    <index>sumgil</index>
    <disableCertificateValidation>true</disableCertificateValidation>
    <layout class="net.logstash.logback.encoder.LogstashEncoder" />
</appender>
```

- URL·토큰은 환경변수로만 받는다(`.env`에 `SPLUNK_HEC_URL`, `SPLUNK_HEC_TOKEN` — 다른 시크릿과 같은 자리, 커밋 금지 원칙 동일 적용).
- 기존 `local, default` 프로필에 바로 끼워 넣지 않고, **새 프로필(`splunk-demo`)에서만 활성화**한다 — 평소 로컬 개발에 영향 안 주고, 데모할 때만 `SPRING_PROFILES_ACTIVE=local,splunk-demo`로 켠다.

```xml
<springProfile name="splunk-demo">
    <root level="INFO">
        <appender-ref ref="SPLUNK_HEC" />
    </root>
</springProfile>
```

## 3. 어떤 이벤트를 "보안 이벤트"로 보여줄지

이 프로젝트엔 로그인·인증이 없어서(공개 API), "인증 실패 로그" 같은 전형적인 보안 이벤트는 없다. 대신 이미 있는 신호를 이상탐지 소재로 재구성한다.

| 소재 | 이미 있는 로그 | Splunk에서 보여줄 것 |
| --- | --- | --- |
| API 오류 스파이크 | `GlobalExceptionHandler`의 `[Domain]`/`[Unhandled]` 로그(`traceId`, `status`, `method`, `uri` MDC 포함) | 시간대별 4xx/5xx 건수 추이, 특정 `uri`에 오류가 몰리는 패턴 |
| 비정상 입력 패턴 | `BAD_REQUEST`·`INVALID_COORDINATE` 등 `ErrorType` 값 | 같은 클라이언트(추정)에서 짧은 시간에 검증 실패가 반복되는 경우를 "무차별 대입/스캐닝 의심"으로 프레이밍 |
| 미확보 리소스 남용 | `STATION_NOT_FOUND`/`ROUTE_NOT_FOUND` 반복 | 존재하지 않는 ID를 연속으로 찔러보는 패턴(정찰 행위 유사) 탐지 |

→ Splunk 대시보드에 "시간대별 오류율", "uri별 오류 Top N", "동일 traceId 반복(짧은 시간 내 다건)" 정도의 검색 3~4개 + 대시보드 1개면 데모로 충분하다.

## 4. 순서

1. Splunk 로컬 설치 + HEC 토큰 발급 (사용자)
2. `build.gradle`에 `splunk-library-javalogging` 의존성 추가
3. `logback-spring.xml`에 `SPLUNK_HEC` appender + `splunk-demo` 프로필 추가
4. `.env.example`에 `SPLUNK_HEC_URL`, `SPLUNK_HEC_TOKEN` 키만 추가(값은 비움)
5. `SPRING_PROFILES_ACTIVE=local,splunk-demo`로 기동해서 실제 API 몇 번 호출 → Splunk에서 인덱싱 확인
6. Splunk 검색 3~4개 + 대시보드 1개 구성
7. (선택) 짧은 스크립트로 오류를 의도적으로 여러 번 발생시켜 "탐지 시나리오" 캡처

이 설계 기준으로 실제 구현(의존성 추가·appender·`.env.example`) 진행할까요?
