package com.ssafy.s15p21a104.consume;

import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import org.springframework.data.redis.core.RedisTemplate;

/**
 * 진짜 Redis 구현 (S15P21A104-171). 직렬화는 {@code RedisConfig} 의 JSON 설정을 그대로 쓴다 —
 * 값이 JSON 이라야 다른 언어(AI 파이썬)도 읽을 수 있다.
 */
public final class RedisTemplateWriter implements RedisWriter {

    private final RedisTemplate<String, Object> template;

    public RedisTemplateWriter(RedisTemplate<String, Object> template) {
        this.template = template;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Optional<Map<String, Object>> get(String key) {
        Object value = template.opsForValue().get(key);
        return value instanceof Map<?, ?> map ? Optional.of((Map<String, Object>) map) : Optional.empty();
    }

    /** @param ttl null 이면 만료를 걸지 않는다 — 상태 키({@code subway:arrival:status})가 그렇다 */
    @Override
    public void set(String key, Map<String, Object> value, Duration ttl) {
        if (ttl == null) {
            template.opsForValue().set(key, value);
        } else {
            template.opsForValue().set(key, value, ttl);
        }
    }
}
