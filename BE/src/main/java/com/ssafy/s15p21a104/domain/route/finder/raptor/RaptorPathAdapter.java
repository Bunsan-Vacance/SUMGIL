package com.ssafy.s15p21a104.domain.route.finder.raptor;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * RAPTOR journey → {@link FoundPath} 어댑터(S15P21A104-217 ③).
 *
 * <p>계약 보존이 목적이다:
 * <ul>
 *   <li><b>C1</b> — BUS 탑승은 corridor 표현({@link BusEdgeBuilder#BUS_CORRIDOR_ROUTE_ID})으로 방출.
 *       FE가 "버스 번호만 다른 후보"를 한 카드로 묶는 계약(234) 유지.</li>
 *   <li><b>C2</b> — 환승 표는 {@link RouteCandidateFinder#transferSeconds}와 동일 함수(단일 규칙).
 *       매퍼의 개수 검증(transferSeconds.size == transferCount)과 어긋나지 않는다.</li>
 *   <li>승차 대기 — 탑승 엣지의 {@code waitSec} 필드에 그대로 싣는다(이동 소요에 합산하지 않는다).
 *       총계에는 모든 탑승 대기를 포함한다 — 응답 매퍼가 leg별 {@code waitMinutes}로 분리한다.</li>
 * </ul>
 *
 * <p>순수 로직 — DB·Spring 비의존.
 */
public final class RaptorPathAdapter {

    private RaptorPathAdapter() {
    }

    /**
     * @param journey 탐색 결과(journey.legs = 접근·탑승·연결·이탈 순서)
     * @param routes {@link RaptorFinder}에 넘긴 노선 목록(leg.routeIndex로 조회)
     * @param transferRule 환승 규칙(환승 실측표 포함)
     * @param busRouteIndex corridor 노선 옵션 인덱스. null이면 routeId 폴백
     */
    public static Optional<FoundPath> toFoundPath(RaptorFinder.Journey journey,
                                                  List<RaptorFinder.Route> routes,
                                                  TransferRule transferRule,
                                                  BusRouteIndex busRouteIndex) {
        if (journey == null || journey.legs().isEmpty()) {
            return Optional.empty();
        }
        List<Edge> edges = new ArrayList<>();
        for (RaptorFinder.Leg leg : journey.legs()) {
            if (leg.routeIndex() >= 0) {
                appendRide(edges, leg, routes.get(leg.routeIndex()));
            } else {
                appendConnection(edges, leg);
            }
        }
        if (edges.isEmpty()) {
            return Optional.empty();
        }
        List<Long> transfers = RouteCandidateFinder.transferSeconds(edges, transferRule, busRouteIndex);
        long totalSec = edges.stream().mapToLong(Edge::travelSec).sum()
                + edges.stream().mapToLong(Edge::waitSec).sum()
                + transfers.stream().mapToLong(Long::longValue).sum();
        List<String> stations = new ArrayList<>();
        stations.add(edges.get(0).fromNode());
        for (Edge edge : edges) {
            stations.add(edge.toNode());
        }
        return Optional.of(new FoundPath(List.copyOf(stations), List.copyOf(edges), totalSec,
                transfers.size()));
    }

    /** 노선 탑승 구간을 정류장 단위 엣지로 전개한다. */
    private static void appendRide(List<Edge> edges, RaptorFinder.Leg leg, RaptorFinder.Route route) {
        String routeId = route.mode() == TravelMode.BUS
                ? BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID
                : route.routeId();
        for (int i = leg.boardIndex(); i < leg.alightIndex(); i++) {
            int travel = route.travelSec()[i];
            int wait = i == leg.boardIndex() ? route.boardWaitSec()[i] : 0;
            edges.add(new Edge(route.stops().get(i), route.stops().get(i + 1), routeId,
                    travel, wait, route.mode()));
        }
    }

    /** 접근·연결·이탈 leg. WALK/BIKE routeId 규칙은 기존 엔진과 동일. */
    private static void appendConnection(List<Edge> edges, RaptorFinder.Leg leg) {
        if (leg.from().equals(leg.to())) {
            // 역 검색의 접근/이탈 0초(A→A)는 기존 엔진 FoundPath에 없는 인공 엣지다 — 만들지 않는다.
            return;
        }
        int sec = (int) Math.max(0, leg.alightSec() - leg.boardSec());
        String routeId = leg.mode() == TravelMode.BIKE
                ? BikeEdgeBuilder.BIKE_ROUTE_ID
                : WalkEdgeBuilder.WALK_ROUTE_ID;
        edges.add(new Edge(leg.from(), leg.to(), routeId, sec, 0,
                leg.mode() == TravelMode.BIKE ? TravelMode.BIKE : TravelMode.WALK));
    }
}
