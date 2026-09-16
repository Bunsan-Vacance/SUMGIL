package com.ssafy.s15p21a104.domain.route.bus;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 정류소 간 BUS 엣지 생성. 순수 로직이며 DB에 접근하지 않는다.
 *
 * <p>노선별 순번 정렬 후 인접 정류소를 방향성 엣지로 잇는다. routeId는 노선 ID
 * 그대로라 노선별 leg 분리가 된다. 버스 속도로 직선거리를 나누어 소요를 산정한다.
 * 좌표 없는 구간·결번은 건너뛰고 값을 채우지 않는다.
 */
public final class BusEdgeBuilder {

    /** 버스 속도(m/s). 20km/h 보수치 (후속 정교화). */
    public static final double METERS_PER_SEC = 20_000.0 / 3600.0;

    /** 지구 반경(m). 하버사인용. */
    private static final double EARTH_R = 6_371_000.0;

    /** 노선 경유 정점. 이름·순번·위도·경도 null 허용(없으면 제외). */
    public record RouteStop(String stopId, String name, Integer seq, Double lat, Double lng) {
        public RouteStop {
            Objects.requireNonNull(stopId, "stopId");
        }

        /** 이름 없이 좌표만으로 만든다 (테스트용). */
        public RouteStop(String stopId, Integer seq, Double lat, Double lng) {
            this(stopId, null, seq, lat, lng);
        }
    }

    private BusEdgeBuilder() {
    }

    /**
     * 노선별 경유 정류소를 순번 정렬 후 인접 구간 BUS 엣지로 잇는다.
     *
     * @param routes 노선 ID → 경유 정류소 목록 (순번 무순 허용, 정렬은 내부 수행)
     * @return BUS 엣지 목록. 해당 구간이 없으면 빈 목록
     */
    public static List<Edge> build(Map<String, List<RouteStop>> routes) {
        List<Edge> edges = new ArrayList<>();
        if (routes == null) {
            return edges;
        }
        for (Map.Entry<String, List<RouteStop>> entry : routes.entrySet()) {
            String routeId = entry.getKey();
            List<RouteStop> stops = new ArrayList<>(entry.getValue());
            stops.sort(Comparator.comparing(RouteStop::seq, Comparator.nullsLast(Integer::compareTo)));
            for (int i = 0; i + 1 < stops.size(); i++) {
                RouteStop from = stops.get(i);
                RouteStop to = stops.get(i + 1);
                if (from.seq() == null || to.seq() == null) {
                    continue;
                }
                if (!hasCoord(from) || !hasCoord(to)) {
                    continue;
                }
                double dist = distanceM(from, to);
                int sec = Math.max(1, (int) Math.round(dist / METERS_PER_SEC));
                edges.add(new Edge(from.stopId(), to.stopId(), routeId, sec, 0, TravelMode.BUS));
            }
        }
        return edges;
    }

    static boolean hasCoord(RouteStop stop) {
        return stop.lat() != null && stop.lng() != null;
    }

    static double distanceM(RouteStop a, RouteStop b) {
        double dLat = Math.toRadians(b.lat() - a.lat());
        double dLng = Math.toRadians(b.lng() - a.lng());
        double h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(a.lat())) * Math.cos(Math.toRadians(b.lat()))
                * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return 2 * EARTH_R * Math.asin(Math.sqrt(h));
    }
}
