package com.ssafy.s15p21a104.load;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;

/** load 프로파일에서만 활성화되는 배선. API 서버 실행에는 아무 영향이 없다. */
@Configuration
@Profile("load")
@EnableConfigurationProperties(LoadProperties.class)
public class LoadConfig {

    @org.springframework.context.annotation.Bean
    UpsertWriter upsertWriter(JdbcTemplate jdbc) {
        return new UpsertWriter(jdbc);
    }
}
