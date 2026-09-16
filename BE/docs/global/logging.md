# 로깅 포맷·정책

> 초기 구축 시점의 설계입니다. 변경될 수 있습니다.

설정은 `src/main/resources/logback-spring.xml`에 있으며 인코더 9.0 (Jackson 3)을 사용합니다.
시간대는 Asia/Seoul이며, `traceId`는 MDC에서 조회합니다 (`MdcLoggingFilter`).

## 정책

| 프로파일 | 콘솔 | 파일 |
|---|---|---|
| `local`·없음 | 텍스트 | JSON (`logs/app-log.json`, 일자 롤링 7일) |
| `prod` | JSON | 없음 |

## 레벨

| 레벨 | 조건 | 스택 포함 여부 |
|---|---|---|
| INFO | 정상 흐름 | 포함하지 않습니다 |
| WARN | 클라이언트 귀책 (4xx) | 포함하지 않습니다 |
| ERROR | 서버 귀책 (5xx) | 포함합니다 |

WARN은 수정 주체가 클라이언트이므로 스택을 남기지 않으며,
ERROR는 서버 결함 후보이므로 스택을 남깁니다.

## 텍스트 형식 (로컬 콘솔)

```
[exec-1  ] --- [550e8400-e29b-41d4-a716-446655440000] c.s.s.route.RouteApi:42  INFO  탐색 요청 from=st_0222 to=st_0239
```

| 위치 | 항목 | 내용 |
|---|---|---|
| `[exec-1  ]` | 스레드 | 요청 처리 스레드이며 병목 추적에 사용합니다 |
| `[550e...]` | traceId | 요청 추적 ID이며 응답 `traceId`와 같습니다. 값이 없으면 `SYSTEM`입니다 |
| `c.s.s.route.RouteApi:42` | 로거:라인 | 로그를 출력한 클래스와 줄 번호입니다 |
| `INFO` | 레벨 | 위 표의 기준을 따릅니다 |
| 뒤 | 메시지 | 로그 본문이며 예외 발생 시 스택이 뒤에 붙습니다 |

## JSON 형식 (로컬 파일, 운영 콘솔)

| 키 | 내용 |
|---|---|
| `@timestamp` | 발생 시각 (KST) |
| `message` | 로그 본문 |
| `logger_name` | 로그를 출력한 클래스 |
| `thread_name` | 스레드 |
| `level` / `level_value` | 레벨 문자열과 수치 (INFO 20000 · WARN 30000 · ERROR 40000) |
| `traceId` | 요청 추적 ID |
| `method` / `uri` / `status` | 요청 정보 (액세스 로그) |
| `hostname` / `pid` | 호스트와 프로세스이며 다중 인스턴스 구분에 사용합니다 |
| `stack_trace` | ERROR에만 포함됩니다 |

### INFO

```json
{"@timestamp":"2026-09-07T10:00:00.000+09:00","message":"GET /api/routes/search -> 200","logger_name":"c.s.s.global.config.MdcLoggingFilter","thread_name":"exec-1","level":"INFO","level_value":20000,"traceId":"550e8400-e29b-41d4-a716-446655440000","method":"GET","uri":"/api/routes/search","status":"200","hostname":"localhost","pid":"12345"}
```

### WARN

```json
{"@timestamp":"2026-09-07T10:00:00.000+09:00","message":"[Domain] GET /api/routes/search -> BAD_REQUEST","logger_name":"c.s.s.global.exception.GlobalExceptionHandler","thread_name":"exec-1","level":"WARN","level_value":30000,"traceId":"550e8400-e29b-41d4-a716-446655440000","hostname":"localhost","pid":"12345"}
```

### ERROR

```json
{"@timestamp":"2026-09-07T10:00:00.000+09:00","message":"[Unhandled] GET /api/routes/search","logger_name":"c.s.s.global.exception.GlobalExceptionHandler","thread_name":"exec-1","level":"ERROR","level_value":40000,"traceId":"550e8400-e29b-41d4-a716-446655440000","stack_trace":"java.lang.NullPointerException: ...","hostname":"localhost","pid":"12345"}
```

## 요청 정보 제외 항목

`params`·`payload`·`headers`·`clientIp`는 적재하지 않습니다.
위치 좌표가 쿼리·본문에 포함되어 로그에 원문을 남기지 않는 원칙과 충돌하기 때문입니다.
(`MdcLoggingFilter` 주석에도 동일 사유를 기록했습니다.)
