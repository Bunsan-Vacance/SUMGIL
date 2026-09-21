package com.ssafy.s15p21a104.domain.buscongestion;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 버스 실시간 혼잡도 조회 설정 (S15P21A104-297). 기본값은 application.yml 에 있고 환경변수로 덮는다.
 *
 * @param enabled      끄면 항상 빈 값이다. 인증키가 없어도 자동으로 꺼진다
 * @param key          공공데이터포털 서비스키(<b>디코딩 키</b>). 로컬은 {@code BE/.env},
 *                     prod 는 {@code be-secret} 의 {@code DATA_GO_KR_KEY}
 * @param dailyCalls   하루 호출 예산. 개발계정이 1,000회/일이라 서버가 끊기 전에 우리가 먼저 멈춘다.
 *                     같은 키를 쓰는 TAGO(10,000/일)와는 활용신청이 달라 예산이 별개다
 * @param cacheTtl     정류소별 캐시 수명. 근거는 {@code CacheKeys.BUS_CONGESTION_TTL} 주석
 * @param readTimeout  호출 하나의 응답 한계. 2026-09-21 실측이 1.5~1.9초라 그보다 조금 넉넉히 둔다
 * @param batchTimeout 한 검색에서 정류소 여러 곳을 받는 전체 한계. 경로 검색 응답이 이만큼보다
 *                     더 늦어지지 않는다 — 넘기면 못 받은 정류소는 그냥 빈 값이다
 * @param nowWindow    "지금 출발" 로 볼 앞뒤 폭. 이 밖의 시각을 지정한 검색에는 붙이지 않는다
 */
@ConfigurationProperties("bus-congestion")
public record BusCongestionProperties(boolean enabled, String key, int dailyCalls, Duration cacheTtl,
                                      Duration readTimeout, Duration batchTimeout, Duration nowWindow) {

    public BusCongestionProperties {
        if (dailyCalls <= 0) {
            dailyCalls = 1000;
        }
        if (cacheTtl == null) {
            cacheTtl = Duration.ofSeconds(30);
        }
        if (readTimeout == null) {
            readTimeout = Duration.ofSeconds(3);
        }
        if (batchTimeout == null) {
            batchTimeout = Duration.ofMillis(1500);
        }
        if (nowWindow == null) {
            nowWindow = Duration.ofMinutes(10);
        }
    }

    /** 인증키가 없으면 켜 두어도 동작하지 않는다 — 배포 순서가 뒤집혀도 안 깨지게 하는 장치다. */
    public boolean usable() {
        return enabled && key != null && !key.isBlank();
    }
}
