package com.ssafy.s15p21a104.domain.route.bus;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
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

    /**
     * 버스 실효 속도(m/s). 14km/h (S15P21A104-216 배치).
     * 직선 거리/20km/h는 실측보다 ~1.5배 짧게 나온다(동일 노선·정류장 네이버 12분
     * 대비 8분 표본). 도로 우회·신호·정차가 합쳐진 값이므로 단일 노브로 두고,
     * 시간표 기반 구간 시각(원빈 트랙)이 들어오면 이 상수는 폐기한다.
     */
    public static final double METERS_PER_SEC = 14_000.0 / 3600.0;

    /** 정규 BUS 엣지의 routeId. 노선 구분 없는 구간 단위 엣지 표시(S15P21A104-234). */
    public static final String BUS_CORRIDOR_ROUTE_ID = "BUS";

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

    /**
     * 정류장 쌍당 BUS 엣지 1개로 정규화한다. 소요는 기존 `build`와 같은 산식(버스 속도·직선거리,
     * 최소 1초), `waitSec`은 0으로 둔다 — headway는 응답 시점에 붙인다.
     */
    public static List<Edge> buildCorridors(Map<String, List<RouteStop>> routes) {
        List<Edge> perRoute = build(routes);
        Map<String, Edge> firstByPair = new LinkedHashMap<>();
        for (Edge edge : perRoute) {
            String key = edge.fromNode() + "->" + edge.toNode();
            firstByPair.putIfAbsent(key, edge);
        }
        List<Edge> corridors = new ArrayList<>();
        for (Edge edge : firstByPair.values()) {
            corridors.add(new Edge(edge.fromNode(), edge.toNode(), BUS_CORRIDOR_ROUTE_ID,
                    edge.travelSec(), 0, TravelMode.BUS));
        }
        return corridors;
    }

    static boolean hasCoord(RouteStop stop) {
        return stop.lat() != null && stop.lng() != null;
    }

    public static double distanceM(RouteStop a, RouteStop b) {
        double dLat = Math.toRadians(b.lat() - a.lat());
        double dLng = Math.toRadians(b.lng() - a.lng());
        double h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(a.lat())) * Math.cos(Math.toRadians(b.lat()))
                * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return 2 * EARTH_R * Math.asin(Math.sqrt(h));
    }
}
