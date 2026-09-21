package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.buscongestion.BusArrival;
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
    private final Function<String, Map<String, BusArrival>> busCongestion;

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
        this(subwayNames, busNames, busRouteIndex, busHeadways, stopId -> Map.of());
    }

    /**
     * @param busCongestion 승차 정류소 ID → 노선별 다음 도착 버스(S15P21A104-297). 실시간 값을
     *                      붙이지 않는 검색(미래 시각)에서는 빈 맵을 돌려주는 함수를 넘긴다
     */
    public RouteNameResolver(
            Function<Set<String>, Map<String, String>> subwayNames,
            Function<Set<String>, Map<String, String>> busNames,
            BusRouteIndex busRouteIndex,
            Function<Set<String>, Map<String, Integer>> busHeadways,
            Function<String, Map<String, BusArrival>> busCongestion) {
        this.subwayNames = subwayNames;
        this.busNames = busNames;
        this.busRouteIndex = busRouteIndex;
        this.busHeadways = busHeadways;
        this.busCongestion = busCongestion == null ? stopId -> Map.of() : busCongestion;
    }

    /**
     * 후보 목록에서 BUS 구간의 승차 정류소를 모은다(S15P21A104-297). 실시간 혼잡도를 미리 받아 둘
     * 대상이고, 버스 구간이 없으면 빈 집합이라 외부 호출이 아예 일어나지 않는다.
     *
     * @param responses 후보 목록
     * @return 승차 정류소 ID 집합(중복 제거)
     */
    public static Set<String> busBoardingStops(List<RouteSearchResponse> responses) {
        Set<String> stops = new java.util.LinkedHashSet<>();
        if (responses == null) {
            return stops;
        }
        for (RouteSearchResponse response : responses) {
            for (RouteLegResponse leg : response.legs()) {
                if (leg.mode() == TravelMode.BUS && leg.fromNodeId() != null && !leg.fromNodeId().isBlank()) {
                    stops.add(leg.fromNodeId());
                }
            }
        }
        return stops;
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
                        RouteLegResponse withName = withRouteName(leg, lineNames, busRouteNames);
                        if (leg.mode() != TravelMode.BUS || leg.routeId() == null) {
                            return withName;
                        }
                        // 노선이 하나로 정해진 BUS 구간도 혼잡도를 붙인다(297).
                        return withName.withCongestionGrade(
                                congestionGrade(leg.fromNodeId(), Set.of(leg.routeId())));
                    })
                    .toList();
            named.add(new RouteSearchResponse(
                    response.routeType(), response.totalMinutes(), legs, response.source(),
                    response.totalDistanceMeters(), response.transferCount(),
                    response.congestionPrediction()));
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
                RouteOptionResponse.of(optionList, names, headways),
                congestionGrade(leg.fromNodeId(), optionIds),
                leg.transitionType(), leg.fromRentalId(), leg.toRentalId()
        );
    }

    /**
     * 구간 대표 혼잡 등급(S15P21A104-297) — 후보 노선 중 <b>가장 먼저 오는</b> 버스의 등급이다.
     * 사용자가 실제로 탈 버스이기 때문이다.
     *
     * <p>조회가 터져도 경로 응답을 깨뜨리지 않는다. 값을 모르면 null 이고 FE 는 "정보 없음" 이 된다.
     *
     * @return 등급 이름. 후보 중 값을 아는 노선이 없거나 조회가 실패하면 null
     */
    private String congestionGrade(String boardingStopId, Set<String> candidateRouteIds) {
        if (boardingStopId == null || boardingStopId.isBlank() || candidateRouteIds.isEmpty()) {
            return null;
        }
        Map<String, BusArrival> arrivals;
        try {
            arrivals = busCongestion.apply(boardingStopId);
        } catch (RuntimeException e) {
            return null;
        }
        return gradeName(arrivals, candidateRouteIds);
    }

    /**
     * 도착 맵에서 후보 노선 중 <b>가장 먼저 오는</b> 버스의 등급 이름(순수, 5부 C1).
     * 표시(297)와 calm 크로스모달 채점이 같은 규칙을 쓰도록 단일 함수로 둔다.
     *
     * @return 등급 이름(예: CONGESTED). 모르면 null
     */
    public static String gradeName(Map<String, BusArrival> arrivals, Set<String> candidateRouteIds) {
        if (arrivals == null || arrivals.isEmpty()
                || candidateRouteIds == null || candidateRouteIds.isEmpty()) {
            return null;
        }
        BusArrival soonest = null;
        for (String routeId : candidateRouteIds) {
            BusArrival arrival = arrivals.get(routeId);
            if (arrival == null) {
                continue;
            }
            soonest = soonest == null ? arrival : soonest.soonerOf(arrival);
        }
        return soonest == null ? null : soonest.grade().name();
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
