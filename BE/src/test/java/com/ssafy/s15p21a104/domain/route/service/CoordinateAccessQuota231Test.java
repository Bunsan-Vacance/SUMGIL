package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-231 접근 후보 유형별 보장 RED.
 * 정류장 밀집지에서도 최근접 역 최소 1곳은 접근 후보에 포함되어야 한다.
 */
class CoordinateAccessQuota231Test {

    @Test
    @DisplayName("231-T1: 정류장 5곳보다 먼 역도 최근접역이라 포함된다")
    void t1_최근접역_보장() {
        // 원점(37.4980,127.0320) 기준: 정류장 4곳(61~266m) + 대여소 1곳(108m) + 역삼역(489m).
        // 기존 로직이면 거리순 상위 5곳에 역이 없어 탈락한다.
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("122000177", new RouteMapper.StationInfo("122000177", "정류장1", 37.4990, 127.0325));
        infos.put("122000201", new RouteMapper.StationInfo("122000201", "정류장2", 37.4985, 127.0323));
        infos.put("122000178", new RouteMapper.StationInfo("122000178", "정류장3", 37.4995, 127.0335));
        infos.put("122000179", new RouteMapper.StationInfo("122000179", "정류장4", 37.4998, 127.0340));
        infos.put("ST-959", new RouteMapper.StationInfo("ST-959", "대여소", 37.4988, 127.0327));
        infos.put("221", new RouteMapper.StationInfo("221", "역삼역", 37.500658, 127.03643));
        RouteGraph graph = RouteTestFixtures.graphOf(
                RouteTestFixtures.subway("221", "222", "L1", 100),
                RouteTestFixtures.subway("222", "221", "L1", 100),
                RouteTestFixtures.bus("122000177", "122000201", "B100", 60),
                RouteTestFixtures.bus("122000201", "122000178", "B100", 60),
                RouteTestFixtures.bus("122000178", "122000179", "B100", 60),
                RouteTestFixtures.bike("ST-959", "ST-960", 60),
                new Edge("ST-960", "ST-960",
                        com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder.BIKE_ROUTE_ID,
                        10, 0, com.ssafy.s15p21a104.domain.route.entity.TravelMode.BIKE));

        List<Edge> edges = CoordinateAccessEdges.accessEdges(
                "PLACE-ORIGIN", 37.4980, 127.0320, infos, graph, true,
                Set.of("221", "222"));

        assertTrue(edges.stream().anyMatch(e -> e.toNode().equals("221")),
                "최근접 역(221)이 접근 후보에 있어야 한다");
    }

    @Test
    @DisplayName("270-T1: 좌표 접근 도보도 우회율(1.3)을 적용한다 — WalkEdgeBuilder 도보 엣지와 같은 산식")
    void t270_좌표접근_우회율() {
        Map<String, RouteMapper.StationInfo> infos = Map.of(
                "221", new RouteMapper.StationInfo("221", "역삼역", 37.500658, 127.03643));
        RouteGraph graph = RouteTestFixtures.graphOf(
                RouteTestFixtures.subway("221", "222", "L1", 100));

        List<Edge> edges = CoordinateAccessEdges.accessEdges(
                "PLACE-ORIGIN", 37.4980, 127.0320, infos, graph, true, Set.of("221", "222"));

        double distanceM = com.ssafy.s15p21a104.global.geo.GeoDistance.haversineMeters(
                37.4980, 127.0320, 37.500658, 127.03643);
        long expected = Math.round(distanceM
                * com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder.CIRCUITY
                / com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder.METERS_PER_SEC);
        assertEquals(expected, edges.get(0).travelSec());
    }
}
