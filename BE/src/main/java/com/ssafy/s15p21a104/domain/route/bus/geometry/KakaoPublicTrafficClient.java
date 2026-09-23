package com.ssafy.s15p21a104.domain.route.bus.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkProperties;
import java.util.Optional;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/** 카카오 대중교통 경로 API 호출기. 도보와 같은 REST 키(app.kakao)를 사용한다. */
@Slf4j
@Component
public class KakaoPublicTrafficClient {

    private static final String BASE_URL = "https://dapi.kakao.com/v2/routing/publictraffic";

    private final KakaoWalkProperties properties;
    private final RestClient restClient;

    public KakaoPublicTrafficClient(KakaoWalkProperties properties) {
        this.properties = properties;
        this.restClient = RestClient.create();
    }

    public Optional<MultiLineStringResponse> fetchGeometry(
            String routeName,
            String fromNodeName,
            String toNodeName,
            double fromLat,
            double fromLng,
            double toLat,
            double toLng) {
        if (!properties.isConfigured()) {
            return Optional.empty();
        }
        try {
            KakaoPublicTrafficResponse response = restClient.get()
                    .uri(BASE_URL + "?start_x={startX}&start_y={startY}&end_x={endX}&end_y={endY}",
                            fromLng, fromLat, toLng, toLat)
                    .header("Authorization", "KakaoAK " + properties.restApiKey())
                    .retrieve()
                    .body(KakaoPublicTrafficResponse.class);
            return KakaoPublicTrafficGeometryMapper.toMultiLineString(
                    response, routeName, fromNodeName, toNodeName,
                    fromLat, fromLng, toLat, toLng);
        } catch (Exception e) {
            log.warn("카카오 버스 경로 조회 실패(빈 geometry로 폴백): {}", e.getMessage());
            return Optional.empty();
        }
    }
}
