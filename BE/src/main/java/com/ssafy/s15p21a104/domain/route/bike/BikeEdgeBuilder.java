package com.ssafy.s15p21a104.domain.route.bike;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 역↔대여소 BIKE 엣지 생성. 순수 로직이며 DB에 접근하지 않는다.
 *
 * <p>자전거 속도로 직선거리를 나누어 소요를 산정한다. 대여·반납 부가시간은 넣지 않는다(후속 정교화).
 * 좌표 없는 정점·반경 밖 쌍은 엣지를 만들지 않는다(값 채우기 금지).
 */
public final class BikeEdgeBuilder {

    /** BIKE 엣지 연결 반경(m). 이보다 먼 쌍은 잇지 않는다. */
    public static final double RADIUS_M = 1000.0;

    /** 자전거 속도(m/s). 15km/h. */
    public static final double METERS_PER_SEC = 15_000.0 / 3600.0;

    /** BIKE 엣지의 routeId. 노선 전환(환승 집계·페널티) 기준이 된다. */
    public static final String BIKE_ROUTE_ID = "BIKE";

    /** 지구 반경(m). 하버사인용. */
    private static final double EARTH_R = 6_371_000.0;

    /** 좌표 보유 정점. 위도·경도 null 허용(없으면 제외). */
    public record Stop(String id, Double lat, Double lng) {
        public Stop {
            Objects.requireNonNull(id, "id");
        }
    }

    private BikeEdgeBuilder() {
    }

    /**
     * 역↔대여소 쌍 중 반경 안을 양방향 BIKE 엣지로 잇는다.
     *
     * @param stations 역 (id → 좌표)
     * @param rentals 대여소 (id → 좌표)
     * @return BIKE 엣지 목록. 해당 쌍이 없으면 빈 목록
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
                edges.add(new Edge(station.id(), rental.id(), BIKE_ROUTE_ID, sec, 0, TravelMode.BIKE));
                edges.add(new Edge(rental.id(), station.id(), BIKE_ROUTE_ID, sec, 0, TravelMode.BIKE));
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
