package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 빌더는 역명을 그대로 ID 로 쓰지 않고 StationIdTable 로 station_id 를 정한다. name 은 표시용 정본 역명으로 남는다.
 * 엣지·환승·슬롯 대기 키도 모두 ID 기준이다. 표에 없는 역이 나오면 적재를 멈춘다(유령 ID 방지).
 */
class SubwayGraphBuilderStationIdTest {

    private static Map<String, String> row(String id, String name, String codes, String source) {
        return Map.of("station_id", id, "name", name, "codes", codes, "source", source);
    }

    private final StationIdTable table = StationIdTable.from(List.of(
            row("150", "서울", "1001:0150;1004:0426", "timetable"),
            row("151", "시청", "1001:0151;1002:0201", "timetable"),
            row("1002", "남영", "1001:1002", "timetable"),
            row("9003", "한남", "", "assigned")));

    private final SubwayGraphBuilder builder = new SubwayGraphBuilder(table);

    private final List<DirectedSegment> directed = List.of(
            new DirectedSegment("1001", "서울", "시청", 120, "timetable"),
            new DirectedSegment("1001", "남영", "서울", 100, "timetable"));

    private final List<Segment> undirected = List.of(new Segment("1063", "한남", "서울", 200, 1800, "avg"));

    private final List<TransferRecord> transfers = List.of(new TransferRecord("서울", "1001", "1004", 180));

    @Test
    @DisplayName("station_id 는 표의 번호, name 은 역명 — 서울 → 150/'서울', 코레일 전용 한남 → 9003")
    void idsFromTableNamesKept() {
        SubwayGraph g = builder.build(directed, undirected, transfers, List.of(), Map.of());

        StationRow seoul = station(g, "150");
        assertEquals("서울", seoul.name());
        assertEquals("한남", station(g, "9003").name());
        assertEquals(4, g.stations().size());
    }

    @Test
    @DisplayName("엣지와 환승 행의 노드도 ID 다 — 150→151, 환승 station_id 150")
    void edgesAndTransfersUseIds() {
        SubwayGraph g = builder.build(directed, undirected, transfers, List.of(), Map.of());

        assertTrue(g.edges().stream().anyMatch(e -> e.fromNode().equals("150") && e.toNode().equals("151")));
        assertTrue(g.edges().stream().anyMatch(e -> e.fromNode().equals("9003") && e.toNode().equals("150")));
        assertEquals("150", g.transfers().get(0).stationId());
    }

    @Test
    @DisplayName("슬롯 대기 키는 역명 키에서 ID 키로 바뀐다 — '1001|서울|시청' → '150|151|1001'")
    void slotWaitsRekeyedToIds() {
        SubwayGraph g = builder.build(directed, undirected, List.of(), List.of(),
                Map.of("1001|서울|시청", SlotWaits.fromDepartures(List.of(List.of(28800), List.of(), List.of()))));

        assertTrue(g.slotWaits().containsKey("150|151|1001"));
    }

    @Test
    @DisplayName("좌표는 역명으로 대조해 ID 행에 붙는다")
    void coordsMatchedByName() {
        SubwayGraph g = builder.build(directed, undirected, List.of(),
                List.of(new StationCoord("1001", "서울", 37.5547, 126.9708, "150")), Map.of());

        assertEquals(37.5547, station(g, "150").lat(), 1e-9);
    }

    @Test
    @DisplayName("표에 없는 역이 나오면 이름을 모아 예외로 멈춘다 — ID 가 몰래 생기지 않게")
    void unknownStationAborts() {
        IllegalStateException e = assertThrows(IllegalStateException.class, () -> builder.build(
                List.of(new DirectedSegment("1001", "서울", "없는역", 100, "timetable")), List.of(), List.of(), List.of(), Map.of()));

        assertTrue(e.getMessage().contains("없는역") && e.getMessage().contains("1001"));
    }

    private static StationRow station(SubwayGraph g, String id) {
        return g.stations().stream().filter(s -> s.stationId().equals(id)).findFirst().orElseThrow();
    }
}
