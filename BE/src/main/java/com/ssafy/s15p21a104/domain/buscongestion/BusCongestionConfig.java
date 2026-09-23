package com.ssafy.s15p21a104.domain.buscongestion;

import com.ssafy.s15p21a104.collect.CallBudget;
import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.collect.http.JdkHttpFetcher;
import java.net.http.HttpClient;
import java.time.Clock;
import java.time.Duration;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.core.RedisTemplate;
import tools.jackson.databind.json.JsonMapper;

/**
 * 버스 실시간 혼잡도 조회 빈 조립 (S15P21A104-297).
 *
 * <p>인증키가 없거나 꺼져 있으면 <b>항상 빈 값을 주는 리더</b>를 올린다. prod 에 GitLab 변수
 * {@code DATA_GO_KR_KEY} 가 등록되기 전에 코드가 먼저 배포돼도 깨지지 않게 하려는 것이다 —
 * 그동안 응답의 {@code congestionGrade} 는 null 이고 FE 는 "정보 없음" 으로 표시한다.
 *
 * <p>재시도는 걸지 않는다. 경로 검색 응답 안에서 도는 조회라 한 번 실패하면 그냥 비우는 편이
 * 낫고, 재시도는 하루 예산만 깎는다(수집기와 다른 점이다).
 */
@Slf4j
@Configuration
@EnableConfigurationProperties(BusCongestionProperties.class)
public class BusCongestionConfig {

    @Bean(destroyMethod = "shutdown")
    public BusCongestionReader busCongestionReader(BusCongestionProperties props,
                                                   RedisTemplate<String, Object> redisTemplate,
                                                   JsonMapper jsonMapper,
                                                   Clock clock) {
        if (!props.usable()) {
            log.info("버스 실시간 혼잡도 비활성 (enabled={} · 인증키 {}) — congestionGrade 는 null 로 나간다",
                    props.enabled(), props.key() == null || props.key().isBlank() ? "없음" : "있음");
            return BusCongestionReader.disabled();
        }
        HttpClient httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(2))
                .build();
        HttpFetcher fetcher = new JdkHttpFetcher(httpClient, props.readTimeout(), props.key());
        log.info("버스 실시간 혼잡도 활성 — 하루 예산 {}회 · 캐시 {}초 · 배치 상한 {}ms · 지금창 ±{}분",
                props.dailyCalls(), props.cacheTtl().toSeconds(), props.batchTimeout().toMillis(),
                props.nowWindow().toMinutes());
        return new BusCongestionReader(fetcher, redisTemplate, jsonMapper,
                new CallBudget(props.dailyCalls(), clock), clock, props.key(),
                props.cacheTtl(), props.batchTimeout());
    }
}
