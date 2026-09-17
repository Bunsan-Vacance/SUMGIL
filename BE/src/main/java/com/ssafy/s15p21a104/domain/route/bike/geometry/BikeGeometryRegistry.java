package com.ssafy.s15p21a104.domain.route.bike.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

/**
 * BIKE leg의 geometry를 요청 시점에 조회해 서버 인스턴스 생존 기간 동안 캐싱한다(S15P21A104-222).
 *
 * <p>{@link com.ssafy.s15p21a104.domain.route.walk.geometry.WalkGeometryRegistry}와 같은
 * 패턴이다 — 기동 시 전체 쌍을 미리 불러오지 않고, 실제 경로 결과에 등장한 대여소 쌍만 호출해
 * 외부 API 쿼터를 최소로 쓴다. 카카오 키 미설정 시 {@link KakaoBikeDirectionsClient}가 항상
 * 빈 값을 주므로 이 레지스트리도 자동으로 무동작(기존 동작 유지)이 된다.
 */
@Component
public class BikeGeometryRegistry {

    private final KakaoBikeDirectionsClient client;
    private final Map<String, Optional<MultiLineStringResponse>> cache = new ConcurrentHashMap<>();

    public BikeGeometryRegistry(KakaoBikeDirectionsClient client) {
        this.client = client;
    }

    /**
     * @param fromNodeId 출발 노드 ID(캐시 키 구성용)
     * @param toNodeId 도착 노드 ID(캐시 키 구성용)
     * @return 조회된 geometry. 미설정·실패·경로 없음이면 빈 값
     */
    public Optional<MultiLineStringResponse> geometryFor(
            String fromNodeId, String toNodeId,
            double fromLat, double fromLng, double toLat, double toLng) {
        String key = fromNodeId + "->" + toNodeId;
        return cache.computeIfAbsent(key,
                k -> client.fetchGeometry(fromLat, fromLng, toLat, toLng));
    }
}
