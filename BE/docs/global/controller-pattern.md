# 표준 컨트롤러 패턴

> 초기 구축 시점의 설계입니다. 변경될 수 있습니다.

요청·응답 DTO와 `*Api`·`*Controller` 분리 예시입니다.
(test API는 문서로 대체되어 삭제됐습니다.)

## 요청 DTO

```java
@Data
@NoArgsConstructor
@AllArgsConstructor
public class EchoRequest {

    @NotBlank(message = "name은 비어 있을 수 없습니다.")
    private String name = "world";

    @Min(value = 1, message = "count는 1 이상이어야 합니다.")
    private int count = 1;
}
```

- 필드에 검증 어노테이션을 둡니다. 기본값을 함께 둡니다.

## 응답 DTO

```java
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class EchoResponse {

    private String greeting;
    private int repeated;
}
```

## 인터페이스

```java
@Tag(name = "Test")
@RequestMapping("/api/v1/test")
public interface TestApi {

    @Operation(summary = "정상 응답")
    @PostMapping("/ok")
    ApiResult<EchoResponse> ok(@Valid @RequestBody EchoRequest request);
}
```

- 매핑·검증·문서 어노테이션은 인터페이스에만 둡니다.

## 구현

```java
@RestController
@RequiredArgsConstructor
public class TestController implements TestApi {

    @Override
    public ApiResult<EchoResponse> ok(EchoRequest request) {
        return ApiResult.ok(EchoResponse.builder()
                .greeting("hello, " + request.getName())
                .repeated(request.getCount())
                .build());
    }
}
```

- 구현에는 `@RestController`와 `@Override`만 둡니다.
- 반환은 `ApiResult.ok(data)`만 사용합니다.
