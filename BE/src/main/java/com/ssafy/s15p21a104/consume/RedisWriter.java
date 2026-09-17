package com.ssafy.s15p21a104.consume;

import java.time.Duration;
import java.util.Map;
import java.util.Optional;

/**
 * 반영기가 Redis 를 보는 창구 (S15P21A104-171). 인터페이스로 두는 이유는 두 가지다.
 *
 * <ul>
 *   <li>반영 규칙(멱등·값 모양)을 Redis 없이 단위 테스트할 수 있다 — collect 쪽 {@code HttpFetcher}/{@code FakeFetcher} 와 같은 결</li>
 *   <li>보험 스위치({@code collect.publisher=redis})에서 수집기가 같은 반영기를 직접 부를 때도 구현만 갈아끼우면 된다</li>
 * </ul>
 */
public interface RedisWriter {

    Optional<Map<String, Object>> get(String key);

    void set(String key, Map<String, Object> value, Duration ttl);
}
