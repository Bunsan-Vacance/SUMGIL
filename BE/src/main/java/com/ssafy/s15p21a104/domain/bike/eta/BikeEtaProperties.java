package com.ssafy.s15p21a104.domain.bike.eta;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 따릉이 AI 실시간 예측 조회 설정 (S15P21A104-309). 기본값은 application.yml 에 있고 환경변수로 덮는다.
 *
 * @param enabled     끄면 항상 빈 값(평균표)이다. AI 주소가 없어도 자동으로 꺼진다
 * @param baseUrl     AI 서버 주소. prod 는 {@code be-config} 의 {@code AI_API_BASE_URL} — 워커 노드의 Tailscale 주소다
 *                    (k3s 노드 IP 가 Tailscale 이라 두 노드의 파드 모두 닿는다, 2026-09-23 실측)
 * @param readTimeout 응답 한계. 2026-09-23 BE 파드 실측이 0.34~0.39초라 넉넉히 둔다. 넘기면 평균표로 나간다
 * @param maxMinutes  이 분을 넘는 도착에는 부르지 않는다 — 모델이 학습한 horizon 상한(5·10·15·30분)
 */
@ConfigurationProperties("bike-eta")
public record BikeEtaProperties(boolean enabled, String baseUrl, Duration readTimeout, int maxMinutes) {

    public BikeEtaProperties {
        if (readTimeout == null) {
            readTimeout = Duration.ofSeconds(1);
        }
        if (maxMinutes <= 0) {
            maxMinutes = 30;
        }
    }

    /** 주소가 없으면 켜 두어도 동작하지 않는다 — 배포 순서가 뒤집혀도 안 깨지게 하는 장치다. */
    public boolean usable() {
        return enabled && baseUrl != null && !baseUrl.isBlank();
    }
}
