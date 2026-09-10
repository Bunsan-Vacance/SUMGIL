package com.ssafy.s15p21a104.domain.route.walk;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder.Stop;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 역↔대여소 WALK 엣지 생성. 순수 로직이며 DB에 접근하지 않는다.
 *
 * <p>도보 속도로 직선거리를 나누어 소요를 산정한다.
 * 좌표 없는 정점·반경 밖 쌍은 엣지를 만들지 않는다(값 채우기 금지).
 */
public final class WalkEdgeBuilder {

    /** WALK 엣지 연결 반경(m). 이보다 먼 쌍은 잇지 않는다. */
    public static final double RADIUS_M = 500.0;

    /** 도보 속도(m/s). 분당 67m. */
    public static final double METERS_PER_SEC = 67.0 / 60.0;

    /** WALK 엣지의 routeId. 노선 전환(환승 집계·페널티) 기준이 된다. */
    public static final String WALK_ROUTE_ID = "WALK";

    /** 지구 반경(m). 하버사인용. */
    private static final double EARTH_R = 6_371_000.0;

    private WalkEdgeBuilder() {
    }

    /**
     * 역↔대여소 쌍 중 반경 안을 양방향 WALK 엣지로 잇는다.
     *
     * @param stations 역 (id → 좌표)
     * @param rentals 대여소 (id → 좌표)
     * @return WALK 엣지 목록. 해당 쌍이 없으면 빈 목록
     */
    public static List<Edge> build(Map<String, Stop> stations, Map<String, Stop> rentals) {
        List<Edge> edges = new ArrayList<>();
        if (stations == null || rentals == null) {
            return edges;
        }
        for (Stop station : stations.values()) {
            if (!hasCoord(station)) {
                continue;
            }
            for (Stop rental : rentals.values()) {
                if (!hasCoord(rental)) {
                    continue;
                }
                double dist = distanceM(station, rental);
                if (dist > RADIUS_M) {
                    continue;
                }
                int sec = (int) Math.round(dist / METERS_PER_SEC);
                edges.add(new Edge(station.id(), rental.id(), WALK_ROUTE_ID, sec, 0, TravelMode.WALK));
                edges.add(new Edge(rental.id(), station.id(), WALK_ROUTE_ID, sec, 0, TravelMode.WALK));
            }
        }
        return edges;
    }

    static boolean hasCoord(Stop stop) {
        return stop.lat() != null && stop.lng() != null;
    }

    static double distanceM(Stop a, Stop b) {
        double dLat = Math.toRadians(b.lat() - a.lat());
        double dLng = Math.toRadians(b.lng() - a.lng());
        double h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(a.lat())) * Math.cos(Math.toRadians(b.lat()))
                * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return 2 * EARTH_R * Math.asin(Math.sqrt(h));
    }
}
