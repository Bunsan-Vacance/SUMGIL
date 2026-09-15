package com.ssafy.s15p21a104.domain.route.walk.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import java.util.Optional;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * 카카오맵 도보 경로 조회 REST API 호출(S15P21A104-186).
 *
 * <p>키 미설정·호출 실패·정상 응답이지만 경로 없음 등 어떤 경우에도 예외를 던지지 않고 빈 값을
 * 반환한다 — 직선으로 만든 가짜 geometry나 가짜 보행 시간을 만들지 않는다는 원칙을 따른다.
 * 호출 측({@link WalkGeometryRegistry})이 빈 값을 "unavailable"로 처리한다.
 */
@Slf4j
@Component
public class KakaoWalkDirectionsClient {

    private final KakaoWalkProperties properties;
    private final RestClient restClient;

    public KakaoWalkDirectionsClient(KakaoWalkProperties properties) {
        this.properties = properties;
        this.restClient = RestClient.create();
    }

    public Optional<MultiLineStringResponse> fetchGeometry(
            double fromLat, double fromLng, double toLat, double toLng) {
        if (!properties.isConfigured()) {
            return Optional.empty();
        }
        try {
            KakaoWalkDirectionsResponse response = restClient.get()
                    .uri(properties.baseUrl()
                                    + "?start_x={startX}&start_y={startY}&end_x={endX}&end_y={endY}",
                            fromLng, fromLat, toLng, toLat)
                    .header("Authorization", "KakaoAK " + properties.restApiKey())
                    .retrieve()
                    .body(KakaoWalkDirectionsResponse.class);
            return KakaoWalkGeometryMapper.toMultiLineString(response);
        } catch (Exception e) {
            log.warn("카카오 도보 경로 조회 실패(빈 geometry로 폴백): {}", e.getMessage());
            return Optional.empty();
        }
    }
}
