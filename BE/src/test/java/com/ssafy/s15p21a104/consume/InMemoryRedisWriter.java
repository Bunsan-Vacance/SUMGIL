package com.ssafy.s15p21a104.consume;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * 단위 테스트용 가짜 Redis. 실제 만료는 흉내내지 않고 TTL 을 기록만 한다 —
 * 만료 동작은 진짜 Redis 를 쓰는 {@code ConsumerKafkaIT} 에서 본다 (collect 쪽 FakeFetcher 와 같은 결).
 */
final class InMemoryRedisWriter implements RedisWriter {

    final Map<String, Map<String, Object>> values = new LinkedHashMap<>();
    final Map<String, Duration> ttls = new LinkedHashMap<>();
    int writes;

    @Override
    public Optional<Map<String, Object>> get(String key) {
        return Optional.ofNullable(values.get(key));
    }

    @Override
    public void set(String key, Map<String, Object> value, Duration ttl) {
        values.put(key, new LinkedHashMap<>(value));
        ttls.put(key, ttl);
        writes++;
    }
}
