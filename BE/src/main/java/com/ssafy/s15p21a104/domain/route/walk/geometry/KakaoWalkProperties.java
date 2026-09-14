package com.ssafy.s15p21a104.domain.route.walk.geometry;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 카카오맵 도보 경로 조회 REST API 설정(S15P21A104-186).
 *
 * <p>{@code restApiKey}가 비어 있으면 {@link KakaoWalkDirectionsClient}는 호출 자체를 하지 않고
 * 항상 빈 값을 반환한다 — 키 발급 전(로컬 개발, CI)에도 기존 동작(geometry unavailable)이 그대로
 * 유지된다. 원천 선정·쿼터·요금은 팀 합의 사항이라(S15P21A104-186) 실제 키는 아직 없다.
 *
 * @param restApiKey 카카오디벨로퍼스 REST API 키. {@code KAKAO_REST_API_KEY} 환경변수로 주입
 * @param baseUrl 도보 경로 조회 엔드포인트. 기본값은 검색으로 확인한 잠정치이며, 실제 사용 전
 *                카카오디벨로퍼스 콘솔 원문 문서로 대조 확인이 필요하다
 */
@ConfigurationProperties("app.kakao")
public record KakaoWalkProperties(String restApiKey, String baseUrl) {

    private static final String DEFAULT_BASE_URL = "https://dapi.kakao.com/v2/routing/walk";

    public KakaoWalkProperties {
        if (baseUrl == null || baseUrl.isBlank()) {
            baseUrl = DEFAULT_BASE_URL;
        }
    }

    public boolean isConfigured() {
        return restApiKey != null && !restApiKey.isBlank();
    }
}
