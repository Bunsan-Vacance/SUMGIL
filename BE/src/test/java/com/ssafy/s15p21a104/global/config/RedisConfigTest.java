package com.ssafy.s15p21a104.global.config;

import com.ssafy.s15p21a104.global.cache.CacheKeys;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.RedisTemplate;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest
class RedisConfigTest {

    @Autowired
    private RedisTemplate<String, Object> redisTemplate;

    @Test
    void JSON_값을_TTL과_함께_쓰고_읽은_뒤_지운다() {
        String key = CacheKeys.bikeStock("test-" + System.nanoTime());
        Map<String, Object> value = Map.of("available", 6);

        redisTemplate.opsForValue().set(key, value, CacheKeys.BIKE_STOCK_TTL);

        assertEquals(value, redisTemplate.opsForValue().get(key));
        assertTrue(redisTemplate.getExpire(key) > 0);

        redisTemplate.delete(key);

        assertFalse(redisTemplate.hasKey(key));
    }
}
