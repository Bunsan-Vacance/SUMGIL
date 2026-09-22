package com.ssafy.s15p21a104.domain.route.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.ssafy.s15p21a104.domain.congestion.scoring.LinkCongestionScorer;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.ScoredCandidate;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.time.LocalDateTime;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * calm 크로스모달 채점 테스트(5부 C1) — 지하철 링크 최대값과 BUS 등급(공통 축)을
 * 같은 축에서 비교한다(2026-09-22: 가중 평균 → 최대값).
 */
class RouteScoreRankerBusTest {

    private static final LocalDateTime DEPART = LocalDateTime.of(2026, 9, 21, 8, 30);

    private static RouteLegResponse leg(TravelMode mode, double minutes) {
        return new RouteLegResponse(mode, "A", "A", 37.5, 127.0, "B", "B", 37.5, 127.1,
                mode.name(), minutes, null, "unavailable", null, null, null);
    }

    private static ScoredCandidate candidate(String routeId, TravelMode mode, int travelSec) {
        return candidateOf(routeId, mode, new Edge("A", "B", routeId, travelSec, 0, mode));
    }

    private static ScoredCandidate candidateOf(String routeId, TravelMode mode, Edge... edges) {
        int totalSec = 0;
        java.util.ArrayList<String> nodes = new java.util.ArrayList<>();
        nodes.add(edges[0].fromNode());
        for (Edge edge : edges) {
            totalSec += edge.travelSec();
            nodes.add(edge.toNode());
        }
        FoundPath path = new FoundPath(nodes, List.of(edges), totalSec, 0);
        RouteSearchResponse response = new RouteSearchResponse(
                RouteType.ALTERNATIVE, totalSec / 60.0, List.of(leg(mode, totalSec / 60.0)),
                RouteSource.ALGORITHM, null, 0, null);
        return new ScoredCandidate(response, path);
    }

    private final RouteScoreRanker ranker =
            new RouteScoreRanker((targetType, targetId, dowType, timeSlot) -> null);

    private static final LinkCongestionScorer.LinkLevelLookup SUBWAY_140 =
            (edge, passThroughTime) -> edge.mode() == TravelMode.SUBWAY ? 140.0 : null;

    private static final RouteScoreRanker.BusLevelLookup BUS_70 =
            leg -> leg.mode() == TravelMode.BUS ? 70.0 : null;

    @Test
    @DisplayName("B1: 지하철 혼잡(140)·버스 여유(70)면 버스가 calm 1등이 된다")
    void b1_크로스모달() {
        ScoredCandidate subway = candidate("L1", TravelMode.SUBWAY, 1800);
        ScoredCandidate bus = candidate("BUS", TravelMode.BUS, 2400);

        List<RouteSearchResponse> ranked = ranker.topCalmByLink(
                List.of(subway, bus), DEPART, SUBWAY_140, 3, BUS_70);

        assertEquals(2, ranked.size());
        assertEquals(RouteType.LOW_CONGESTION, ranked.get(0).routeType());
        assertEquals(40.0, ranked.get(0).totalMinutes(), 0.01); // 버스가 1등
    }

    @Test
    @DisplayName("B2: 버스 등급을 모르면 기존과 동일 — 지하철 링크 점수만으로 정렬(버스는 점수 없음)")
    void b2_버스미지() {
        ScoredCandidate subway = candidate("L1", TravelMode.SUBWAY, 1800);
        ScoredCandidate bus = candidate("BUS", TravelMode.BUS, 2400);

        List<RouteSearchResponse> ranked = ranker.topCalmByLink(
                List.of(subway, bus), DEPART, SUBWAY_140, 3);

        assertEquals(1, ranked.size());
        assertEquals(RouteType.LOW_CONGESTION, ranked.get(0).routeType());
        assertEquals(30.0, ranked.get(0).totalMinutes(), 0.01);
    }

    @Test
    @DisplayName("B3: 평균이면 지하철이 1등이지만, 최대 기준이면 버스가 1등이다")
    void b3_최대값이_순위를_바꾼다() {
        // 지하철: 30분 구간 10 + 1분 구간 200 → 평균 16.1, 최대 200
        ScoredCandidate subway = candidateOf("L1", TravelMode.SUBWAY,
                new Edge("A", "B", "L1", 1800, 0, TravelMode.SUBWAY),
                new Edge("B", "C", "L1", 60, 0, TravelMode.SUBWAY));
        ScoredCandidate bus = candidate("BUS", TravelMode.BUS, 2400);
        LinkCongestionScorer.LinkLevelLookup lookup = (edge, t) ->
                TravelMode.SUBWAY == edge.mode()
                        ? (edge.fromNode().equals("A") ? 10.0 : 200.0) : null;

        List<RouteSearchResponse> ranked = ranker.topCalmByLink(
                List.of(subway, bus), DEPART, lookup, 3, BUS_70);

        assertEquals(2, ranked.size());
        assertEquals(RouteType.LOW_CONGESTION, ranked.get(0).routeType());
        assertEquals(40.0, ranked.get(0).totalMinutes(), 0.01); // 최대 70인 버스가 1등
    }
}
