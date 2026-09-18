package com.ssafy.s15p21a104.domain.route.bus;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 정류장 쌍별 운행 노선 인덱스(S15P21A104-234).
 *
 * <p>탐색 그래프에는 구간당 BUS 엣지 1개만 두고({@link BusEdgeBuilder#buildCorridors}),
 * 노선 목록은 여기서 보관한다. DB·Spring 비의존 순수 함수.
 */
public final class BusRouteIndex {

    public record StopPair(String from, String to) {
    }

    private final Map<StopPair, List<String>> routesByPair;

    private BusRouteIndex(Map<StopPair, List<String>> routesByPair) {
        this.routesByPair = Map.copyOf(routesByPair);
    }

    /**
     * 노선별 경유 목록에서 구간별 노선 목록을 만든다. 노선 ID는 정렬해 고정 순서로 둔다.
     */
    public static BusRouteIndex build(Map<String, List<BusEdgeBuilder.RouteStop>> routes) {
        Map<StopPair, Set<String>> acc = new LinkedHashMap<>();
        if (routes != null) {
            List<String> routeIds = new ArrayList<>(routes.keySet());
            java.util.Collections.sort(routeIds);
            for (String routeId : routeIds) {
                List<BusEdgeBuilder.RouteStop> stops = new ArrayList<>(
                        routes.getOrDefault(routeId, List.of()));
                stops.sort(java.util.Comparator.comparing(
                        BusEdgeBuilder.RouteStop::seq,
                        java.util.Comparator.nullsLast(Integer::compareTo)));
                for (int i = 0; i + 1 < stops.size(); i++) {
                    BusEdgeBuilder.RouteStop from = stops.get(i);
                    BusEdgeBuilder.RouteStop to = stops.get(i + 1);
                    if (from.seq() == null || to.seq() == null) {
                        continue;
                    }
                    acc.computeIfAbsent(new StopPair(from.stopId(), to.stopId()),
                                    k -> new LinkedHashSet<>())
                            .add(routeId);
                }
            }
        }
        Map<StopPair, List<String>> done = new LinkedHashMap<>();
        acc.forEach((pair, ids) -> done.put(pair, List.copyOf(ids)));
        return new BusRouteIndex(done);
    }

    /** 해당 구간 운행 노선. 없으면 빈 목록 (값을 지어내지 않는다). */
    public List<String> routesFor(String from, String to) {
        return routesByPair.getOrDefault(new StopPair(from, to), List.of());
    }

    /**
     * 엣지의 운행 노선 집합. 정규 BUS 엣지(`BUS_CORRIDOR_ROUTE_ID`)는 인덱스에서,
     * 그 외 엣지(기존 per-route 엣지·비BUS)는 자신의 routeId 1건을 돌려준다.
     * 인덱스가 null이어도 routeId로 폴백한다.
     */
    public static Set<String> optionsFor(Edge edge, BusRouteIndex index) {
        Objects.requireNonNull(edge, "edge");
        if (edge.mode() == TravelMode.BUS
                && BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID.equals(edge.routeId())
                && index != null) {
            return Set.copyOf(new LinkedHashSet<>(index.routesFor(edge.fromNode(), edge.toNode())));
        }
        return Set.of(edge.routeId());
    }
}
