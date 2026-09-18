package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteOptionResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

/**
 * 노선 이름 배치(S15P21A104-213 T4).
 *
 * <p>{@code RouteSearchService}에서 분리했다. SUBWAY는 line.name, BUS는
 * bus_route.name을 배치로 붙인다(FE-175 항목8). 그 외 수단은 null로 둔다.
 * 이름 조회는 함수로 주입한다. DB에 직접 의존하지 않는다.
 */
public final class RouteNameResolver {

    private final Function<Set<String>, Map<String, String>> subwayNames;
    private final Function<Set<String>, Map<String, String>> busNames;
    private final BusRouteIndex busRouteIndex;
    private final Function<Set<String>, Map<String, Integer>> busHeadways;

    public RouteNameResolver(
            Function<Set<String>, Map<String, String>> subwayNames,
            Function<Set<String>, Map<String, String>> busNames) {
        this(subwayNames, busNames, null, ids -> Map.of());
    }

    public RouteNameResolver(
            Function<Set<String>, Map<String, String>> subwayNames,
            Function<Set<String>, Map<String, String>> busNames,
            BusRouteIndex busRouteIndex,
            Function<Set<String>, Map<String, Integer>> busHeadways) {
        this.subwayNames = subwayNames;
        this.busNames = busNames;
        this.busRouteIndex = busRouteIndex;
        this.busHeadways = busHeadways;
    }

    /**
     * 후보 목록에 사람이 읽는 노선 이름을 배치로 붙인다.
     *
     * @param responses 후보 목록
     * @return 노선명이 붙은 후보 목록
     */
    public List<RouteSearchResponse> withRouteNames(List<RouteSearchResponse> responses) {
        java.util.Set<String> subwayLineIds = new java.util.HashSet<>();
        java.util.Set<String> busRouteIds = new java.util.HashSet<>();
        for (RouteSearchResponse response : responses) {
            for (RouteLegResponse leg : response.legs()) {
                if (leg.routeId() == null) {
                    continue;
                }
                if (leg.mode() == TravelMode.SUBWAY) {
                    subwayLineIds.add(leg.routeId());
                } else if (leg.mode() == TravelMode.BUS) {
                    busRouteIds.add(leg.routeId());
                }
            }
        }
        Map<String, String> lineNames = subwayNames.apply(subwayLineIds);
        Map<String, String> busRouteNames = busNames.apply(busRouteIds);

        List<RouteSearchResponse> named = new java.util.ArrayList<>();
        for (RouteSearchResponse response : responses) {
            List<RouteLegResponse> legs = response.legs().stream()
                    .map(leg -> {
                        if (leg.mode() == TravelMode.BUS
                                && BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID.equals(leg.routeId())) {
                            return withBusOptions(leg);
                        }
                        return withRouteName(leg, lineNames, busRouteNames);
                    })
                    .toList();
            named.add(new RouteSearchResponse(
                    response.routeType(), response.totalMinutes(), legs, response.source(),
                    response.totalDistanceMeters(), response.transferCount()));
        }
        return named;
    }

    /**
     * 정규 BUS 구간 leg에 운행 노선 후보를 붙인다(S15P21A104-234).
     * 구간 단위라 노선 선택을 미루고 목록으로 싣는다. 단일 routeName은 null로 둔다.
     * 매퍼가 묶음 교집합으로 싣고 온 ID를 우선 쓰고(다정거장 ride의 빈 옵션 방지),
     * 없을 때만 양끝점 조회로 폴백한다(기존 2-arg 경로 동일).
     */
    private RouteLegResponse withBusOptions(RouteLegResponse leg) {
        Set<String> optionIds = leg.routeOptions() != null
                ? leg.routeOptions().stream().map(RouteOptionResponse::routeId)
                        .collect(java.util.stream.Collectors.toCollection(java.util.LinkedHashSet::new))
                : BusRouteIndex.optionsFor(
                        new Edge(leg.fromNodeId(), leg.toNodeId(), leg.routeId(), 0, 0, leg.mode()),
                        busRouteIndex);
        List<String> optionList = optionIds.stream().sorted().toList();
        Map<String, String> names = busNames.apply(optionIds);
        Map<String, Integer> headways = busHeadways.apply(optionIds);
        return new RouteLegResponse(
                leg.mode(),
                leg.fromNodeId(), leg.fromNodeName(), leg.fromLat(), leg.fromLng(),
                leg.toNodeId(), leg.toNodeName(), leg.toLat(), leg.toLng(),
                leg.routeId(), leg.minutes(),
                leg.geometry(), leg.geometryStatus(),
                leg.distanceMeters(), null,
                RouteOptionResponse.of(optionList, names, headways)
        );
    }

    private static RouteLegResponse withRouteName(
            RouteLegResponse leg, Map<String, String> lineNames, Map<String, String> busNames) {
        String routeName = switch (leg.mode()) {
            case SUBWAY -> lineNames.get(leg.routeId());
            case BUS -> busNames.get(leg.routeId());
            default -> null;
        };
        if (routeName == null) {
            return leg;
        }
        return new RouteLegResponse(
                leg.mode(),
                leg.fromNodeId(), leg.fromNodeName(), leg.fromLat(), leg.fromLng(),
                leg.toNodeId(), leg.toNodeName(), leg.toLat(), leg.toLng(),
                leg.routeId(), leg.minutes(),
                leg.geometry(), leg.geometryStatus(),
                leg.distanceMeters(), routeName, null
        );
    }
}
