package com.ssafy.s15p21a104.global.config;

import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * FE 개발 서버 CORS 허용 목록. 기본값은 application.yml 에 있고, 각자 로컬 환경(IP·포트)이 다르면
 * {@code APP_CORS_ALLOWED_ORIGINS}(콤마 구분) 환경변수로 덮어쓴다.
 *
 * @param allowedOrigins 허용할 출처(scheme+host+port) 목록. 정확히 일치해야 한다 — 와일드카드 미사용
 */
@ConfigurationProperties("app.cors")
public record CorsProperties(List<String> allowedOrigins) {

    public CorsProperties {
        if (allowedOrigins == null) {
            allowedOrigins = List.of();
        }
    }
}
