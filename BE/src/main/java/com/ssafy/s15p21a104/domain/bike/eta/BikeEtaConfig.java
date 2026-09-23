package com.ssafy.s15p21a104.domain.bike.eta;

import com.ssafy.s15p21a104.collect.http.JdkHttpFetcher;
import java.net.http.HttpClient;
import java.time.Clock;
import java.time.Duration;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import tools.jackson.databind.json.JsonMapper;

/**
 * 따릉이 AI 실시간 예측 조회 빈 조립 (S15P21A104-309).
 *
 * <p>AI 주소가 없거나 꺼져 있으면 <b>항상 빈 값을 주는 리더</b>를 올린다 — 도착 예측은 그동안 평균표로 나간다.
 * 로컬·테스트는 주소가 없으니 자동으로 꺼진다(버스 혼잡도 297 과 같은 구성).
 */
@Slf4j
@Configuration
@EnableConfigurationProperties(BikeEtaProperties.class)
public class BikeEtaConfig {

    @Bean
    public BikeEtaReader bikeEtaReader(BikeEtaProperties props, JsonMapper jsonMapper, Clock clock) {
        if (!props.usable()) {
            log.info("따릉이 AI 실시간 예측 비활성 (enabled={} · 주소 {}) — 도착 예측은 평균표로 나간다",
                    props.enabled(), props.baseUrl() == null || props.baseUrl().isBlank() ? "없음" : "있음");
            return BikeEtaReader.disabled();
        }
        HttpClient httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(1))
                .build();
        log.info("따릉이 AI 실시간 예측 활성 — {} · 응답 한계 {}ms · {}분 이내 도착만",
                props.baseUrl(), props.readTimeout().toMillis(), props.maxMinutes());
        return new BikeEtaReader(new JdkHttpFetcher(httpClient, props.readTimeout(), null), jsonMapper, clock,
                props.baseUrl(), props.maxMinutes());
    }
}
