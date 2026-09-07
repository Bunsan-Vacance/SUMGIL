# 비즈니스 구현 가이드 (global 사용법)

> 초기 구축 시점의 설계입니다. 변경될 수 있습니다.

## 컨트롤러

- 반환값은 `ApiResult.ok(data)`만 사용합니다. `ResponseEntity`를 직접 사용하지 않습니다.
- 매핑·검증·문서 어노테이션은 `*Api` 인터페이스에 둡니다.
  예시: `@GetMapping`·`@RequestBody`·`@Valid`·`@Tag`·`@Operation`.
- `*Controller`에는 `@RestController`와 `@Override`만 둡니다.
  파라미터 어노테이션을 작성하지 않습니다.

## 서비스

- 실패는 `throw new DomainException(에러코드)` 한 줄로 처리합니다. try-catch를 작성하지 않습니다.
- 컨트롤러 계층 이상에서는 try-catch를 작성하지 않습니다.
  새로운 실패 양식은 `ErrorType`에 코드로 먼저 선언한 뒤 던집니다.
  코드 없이 예외를 던지지 않습니다.
- 복구할 수 있는 예외도 `catch`로 은폐하지 말고 `DomainException`으로 변환하여 던집니다.
  자원 정리가 필요할 때만 catch 후 rethrow합니다.

## 도메인 에러 추가

1. `ErrorType` enum에 한 줄을 추가합니다.
   예시: `BUS_ROUTE_NOT_FOUND(404, "BUS_ROUTE_NOT_FOUND", "노선을 찾을 수 없습니다.")`
2. 서비스에서 `throw new DomainException(ErrorType.BUS_ROUTE_NOT_FOUND)`를 던집니다.
3. 핸들러와 응답 모양은 수정할 필요가 없습니다.

## 검증

- 요청 DTO 필드에 `@NotBlank`·`@Min` 등의 제약을 붙입니다.
- 컨트롤러 파라미터에 `@Valid`를 붙입니다. 검증 실패 시 400 고정 메시지로 응답되며,
  필드별 상세 내용은 로그에만 남습니다.

## 로그·추적

- 별도 작업이 필요 없습니다. 필터가 traceId를 설정하고 로그·응답에 자동 포함됩니다.
- 수동 로그는 `log.info/warn/error`만 사용합니다.
