# global 설계

> 초기 구축 시점의 설계입니다. 변경될 수 있습니다.

`api`와 `domain`에서 공통으로 사용하는 기반 코드이며 비즈니스 로직을 포함하지 않습니다.

## response

- `ApiResult<T>`는 응답 래퍼 `{success, timestamp, traceId, data, error}`입니다.
  컨트롤러는 `ok(data)`만 반환합니다. `NON_NULL` 설정에 따라 성공 응답에서는 `error` 키가,
  실패 응답에서는 `data` 키가 제외됩니다.
- `TraceId`는 MDC에서 traceId를 조회합니다. 필터가 항상 값을 설정하므로
  `N/A` 반환은 방어용으로만 존재합니다.
- 성공과 실패를 하나의 형태로 반환하므로 클라이언트의 응답 처리가 통일됩니다.
  HTTP 상태 코드는 상태 라인에 담고, 실패 사유는 `error`에 담습니다.

### 성공 (HTTP 200)

```json
{
  "success": true,
  "timestamp": "2026-09-07T10:00:00+09:00",
  "traceId": "550e8400-e29b-41d4-a716-446655440000",
  "data": { "id": 1, "name": "강남" }
}
```

### 실패 (HTTP 404)

```json
{
  "success": false,
  "timestamp": "2026-09-07T10:00:00+09:00",
  "traceId": "550e8400-e29b-41d4-a716-446655440000",
  "error": { "status": 404, "code": "NOT_FOUND", "message": "요청한 리소스를 찾을 수 없습니다." }
}
```

## exception

- 에러 코드는 `ErrorType` 하나로 관리합니다. 새 도메인 코드는 enum에 직접 추가하며,
  추가 방법은 [usage.md](usage.md)에 정리되어 있습니다.
- `ErrorType`은 공통 코드 4종과 도메인 코드를 함께 정의합니다.
- `DomainException`은 서비스 계층이 던지는 유일한 예외입니다.
  스택 트레이스를 생성하지 않습니다 (`fillInStackTrace`).
- `GlobalExceptionHandler`는 예외 변환을 전담합니다.
  `DomainException`은 해당 코드로 변환합니다.
  Spring 예외는 파라미터 누락·타입 불일치·JSON 파싱 실패를 400으로,
  존재하지 않는 경로를 404로, 미지원 메서드를 405로 변환합니다.
  검증 실패는 400 고정 메시지로 변환하며, 필드별 상세 내용은 로그에만 남깁니다.
  그 외의 예외는 500으로 변환합니다.
  모든 결과는 래퍼 형태로 반환됩니다.
- Fail-fast 원칙을 따릅니다. 복구하지 않는 catch를 작성하지 않으며,
  예외를 던져 핸들러에 위임합니다.

## config

- `MdcLoggingFilter`는 `X-Trace-Id`를 수용 또는 발급하고 응답 헤더에 에코하며
  MDC에 적재합니다. 로그의 traceId와 응답의 traceId가 일치합니다.
- `SwaggerConfig`는 `/api/**` 경로를 `public-api` 그룹으로 문서화합니다.
  인증이 없으므로 보안 항목을 포함하지 않습니다.
- `JpaConfig`는 `@EnableJpaAuditing`을 활성화합니다.
  감사 컬럼을 사용하는 엔티티가 추가되면 `BaseTimeEntity`와 함께 동작합니다.
- `RedisConfig`는 `RedisTemplate<String, Object>` 빈을 등록합니다.
  키는 문자열, 값은 JSON(`GenericJacksonJsonRedisSerializer`)으로 직렬화합니다.
  Spring Boot 기본 템플릿(JDK 직렬화)은 Spark/Python 등 다른 언어가 쓴 값을 못 읽어서 쓰지 않습니다.

## cache

- `CacheKeys`는 Redis 키 네이밍 규칙과 TTL 상수를 한곳에서 관리합니다.
  새 캐시 종류가 필요하면 이 클래스와 [cache/strategy.md](../cache/strategy.md)에 함께 추가합니다.
- 실제 캐시 채움(사전계산 결과 적재, 스트림 갱신)은 데이터 파이프라인 연동 후 구현합니다.
  지금은 키·TTL 정책과 `RedisTemplate` 연동까지만 되어 있습니다.

## common

- `BaseCreatedTimeEntity`는 `created_at`만 관리합니다.
  생성 시점만 의미가 있는 테이블에 사용합니다.
  예시: 적재 실행 이력(`job_run`), 에러 로그.
- `BaseTimeEntity`는 `created_at`과 `updated_at`을 관리합니다.
  애플리케이션이 직접 작성하고 수정하는 테이블에 사용합니다.
  예시: 세션·즐겨찾기 (향후 추가 시).
- 적재 테이블(`edge_time` 등)은 위 클래스를 상속하지 않습니다.
  `updated_at`을 적재 프로세스가 직접 기록하므로 일반 컬럼으로 둡니다.
