package com.ssafy.s15p21a104.domain.route.walk.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

/**
 * 역↔대여소 WALK leg의 geometry를 요청 시점에 조회해 서버 인스턴스 생존 기간 동안 캐싱한다
 * (S15P21A104-186).
 *
 * <p>{@link com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry}와 달리 기동 시
 * 전체 쌍을 미리 불러오지 않는다 — 실제 경로 결과에 등장한 쌍만 호출해 외부 API 쿼터를 최소로
 * 쓴다. 카카오 키 미설정 시 {@link KakaoWalkDirectionsClient}가 항상 빈 값을 주므로 이 레지스트리도
 * 자동으로 무동작(기존 동작 유지)이 된다.
 */
@Component
public class WalkGeometryRegistry {

    private final KakaoWalkDirectionsClient client;
    private final Map<String, Optional<MultiLineStringResponse>> cache = new ConcurrentHashMap<>();

    public WalkGeometryRegistry(KakaoWalkDirectionsClient client) {
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
        return cache.computeIfAbsent(
                keyOf(fromNodeId, toNodeId, fromLat, fromLng, toLat, toLng),
                k -> client.fetchGeometry(fromLat, fromLng, toLat, toLng));
    }

    /**
     * 캐시 키에 좌표를 포함한다 — 노드 ID만 쓰면 임시 장소 노드(PLACE-ORIGIN/PLACE-DEST)처럼
     * ID가 고정이고 좌표가 요청마다 바뀌는 노드에서 다른 요청의 지오메트리를 재사용해
     * 표시 거리·시간이 오염된다(2026-09-21 prod 실측). 노드 쌍의 좌표는 보통 고정이라
     * 기존 쌍에는 영향이 없다. 좌표는 6자리(≈0.1m)로 반올림해 키를 안정화한다.
     */
    static String keyOf(String fromNodeId, String toNodeId,
            double fromLat, double fromLng, double toLat, double toLng) {
        return fromNodeId + "->" + toNodeId
                + "@" + String.format(java.util.Locale.ROOT, "%.6f,%.6f>%.6f,%.6f",
                        fromLat, fromLng, toLat, toLng);
    }
}
