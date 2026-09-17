package com.ssafy.s15p21a104.global.config;

import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** API 서버 전역에서 쓰는 시각 기준. 프로파일 제한 없이 항상 뜬다 — 신선도 판정처럼 "지금"이 필요한 도메인 코드가 테스트 가능하도록. */
@Configuration
public class ClockConfig {

    @Bean
    public Clock clock() {
        return Clock.systemDefaultZone();
    }
}
