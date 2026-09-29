package com.ssafy.s15p21a104.domain.route.bus.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

/** BUS leg의 실제 도로 geometry를 조회하고 성공 결과만 캐시한다. */
@Component
public class BusGeometryRegistry {

    private final KakaoPublicTrafficClient client;
    private final Map<String, MultiLineStringResponse> cache = new ConcurrentHashMap<>();

    public BusGeometryRegistry(KakaoPublicTrafficClient client) {
        this.client = client;
    }

    public Optional<MultiLineStringResponse> geometryFor(
            String routeId,
            String fromNodeId,
            String toNodeId,
            String routeName,
            String fromNodeName,
            String toNodeName,
            double fromLat,
            double fromLng,
            double toLat,
            double toLng) {
        String key = routeId + "->" + fromNodeId + "->" + toNodeId + "->" + routeName;
        MultiLineStringResponse cached = cache.get(key);
        if (cached != null) {
            return Optional.of(cached);
        }
        Optional<MultiLineStringResponse> fetched = client.fetchGeometry(
                routeName, fromNodeName, toNodeName, fromLat, fromLng, toLat, toLng);
        fetched.ifPresent(value -> cache.putIfAbsent(key, value));
        return fetched;
    }
}
