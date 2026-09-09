package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 시각표에서 온 방향 있는 구간은 역방향을 만들지 않고, 코레일 거리 구간(무방향)은 지금처럼 양방향으로 만든다.
 * 슬롯별 대기는 역명 키에서 station_id 키(from|to|route)로 옮겨 그래프에 실린다.
 */
class SubwayGraphBuilderDirectedTest {

    private final SubwayGraphBuilder builder = new SubwayGraphBuilder(Map.of("신촌|1063", "신촌_경의중앙"));

    private final List<DirectedSegment> directed = List.of(
            new DirectedSegment("1006", "응암", "역촌", 120, "timetable"),
            new DirectedSegment("1006", "역촌", "불광", 120, "timetable"),
            new DirectedSegment("1002", "강남", "역삼", 120, "timetable"),
            new DirectedSegment("1002", "역삼", "강남", 130, "timetable"));

    private final List<Segment> undirected = List.of(
            new Segment("1063", "신촌", "서강대", 150, 1400, "avg"));

    private final Map<String, SlotWaits> waitsByName = Map.of(
            "1002|강남|역삼", SlotWaits.fromDepartures(List.of(List.of(28800, 29400, 30000, 30600), List.of(), List.of())));

    @Test
    @DisplayName("방향 있는 구간은 그 방향 엣지 하나만 만든다 — 응암→역촌만 있고 역촌→응암은 없다")
    void directedSegmentsMakeOneEdge() {
        SubwayGraph g = builder.build(directed, undirected, List.of(), List.of(), waitsByName);

        assertTrue(g.edges().stream().anyMatch(e -> e.fromNode().equals("응암") && e.toNode().equals("역촌")));
        assertTrue(g.edges().stream().noneMatch(e -> e.fromNode().equals("역촌") && e.toNode().equals("응암")));
    }

    @Test
    @DisplayName("반대 방향 구간이 따로 있으면 각자의 소요시간을 갖는다 — 강남→역삼 120, 역삼→강남 130")
    void oppositeDirectionsKeepOwnTravel() {
        SubwayGraph g = builder.build(directed, undirected, List.of(), List.of(), waitsByName);

        assertEquals(120, edge(g, "강남", "역삼").travelSec());
        assertEquals(130, edge(g, "역삼", "강남").travelSec());
    }

    @Test
    @DisplayName("무방향 구간(코레일 거리)은 지금처럼 양방향 엣지가 되고 동명이역 예외 표를 거친다")
    void undirectedSegmentsStillMakeBothEdges() {
        SubwayGraph g = builder.build(directed, undirected, List.of(), List.of(), waitsByName);

        assertNotNull(edge(g, "신촌_경의중앙", "서강대"));
        assertNotNull(edge(g, "서강대", "신촌_경의중앙"));
        assertEquals(6, g.edges().size());
    }

    @Test
    @DisplayName("역과 노선은 두 종류 구간에서 모두 모인다")
    void stationsAndLinesFromBoth() {
        SubwayGraph g = builder.build(directed, undirected, List.of(), List.of(), waitsByName);

        assertEquals(Set.of("1006", "1002", "1063"),
                g.lines().stream().map(LineRow::lineId).collect(java.util.stream.Collectors.toSet()));
        assertEquals(7, g.stations().size());
    }

    @Test
    @DisplayName("슬롯별 대기는 station_id 기준 엣지 키(from|to|route)로 그래프에 실리고, 없는 엣지는 키가 없다")
    void slotWaitsAreRekeyedByStationId() {
        SubwayGraph g = builder.build(directed, undirected, List.of(), List.of(), waitsByName);

        assertTrue(g.slotWaits().containsKey("강남|역삼|1002"));
        assertEquals(1, g.slotWaits().size());
        assertTrue(g.slotWaits().get("강남|역삼|1002").wait(0, 16) > 0);
    }

    @Test
    @DisplayName("기존 3인자 build 는 그대로 동작하고 슬롯 대기는 비어 있다")
    void legacyBuildStillWorks() {
        SubwayGraph g = builder.build(undirected, List.of(), List.of());

        assertEquals(2, g.edges().size());
        assertTrue(g.slotWaits().isEmpty());
    }

    private static EdgeRow edge(SubwayGraph g, String from, String to) {
        return g.edges().stream().filter(e -> e.fromNode().equals(from) && e.toNode().equals(to)).findFirst().orElse(null);
    }
}
