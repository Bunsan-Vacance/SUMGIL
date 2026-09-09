package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 구간·환승·좌표를 합쳐 적재용 그래프를 만든다.
 * station_id 는 정규화 역명이며(물리 역 1행), 동명이역은 (역명|노선) 예외 표로 갈라낸다.
 */
class SubwayGraphBuilderTest {

    private final List<Segment> segments = List.of(
            new Segment("1002", "상왕십리", "왕십리", 60, 900, "timetable"),
            new Segment("1002", "왕십리", "한양대", 90, 1000, "timetable"),
            new Segment("1005", "행당", "왕십리", 80, 900, "timetable"));

    private final List<TransferRecord> transfers = List.of(
            new TransferRecord("왕십리", "1002", "1005", 72),
            new TransferRecord("왕십리", "1005", "1002", 72),
            new TransferRecord("왕십리", "1002", "1075", 83));

    private final List<StationCoord> coords = List.of(
            new StationCoord("1002", "왕십리", 37.5612, 127.0376, "208"),
            new StationCoord("1005", "왕십리", 37.5613, 127.0377, "2541"),
            new StationCoord("1002", "한양대", 37.5556, 127.0437, "209"));

    private final SubwayGraphBuilder builder = new SubwayGraphBuilder(StationIdTable.identity());

    @Test
    @DisplayName("구간에 등장한 역이 물리 역 1행씩 만들어지고 소속 노선을 모은다")
    void buildsPhysicalStations() {
        SubwayGraph g = builder.build(segments, transfers, coords);

        assertEquals(4, g.stations().size());
        StationRow wangsimni = g.stations().stream().filter(s -> s.stationId().equals("왕십리")).findFirst().orElseThrow();
        assertEquals("왕십리", wangsimni.name());
        assertEquals(Set.of("1002", "1005"), wangsimni.lineIds());
    }

    @Test
    @DisplayName("좌표는 소속 노선의 좌표 파일 값을 쓰고, 없으면 null 로 둔다 (채워 넣지 않는다)")
    void coordinatesFromCoordsOrNull() {
        SubwayGraph g = builder.build(segments, transfers, coords);

        StationRow wangsimni = g.stations().stream().filter(s -> s.stationId().equals("왕십리")).findFirst().orElseThrow();
        assertEquals(37.5612, wangsimni.lat(), 1e-9);
        StationRow haengdang = g.stations().stream().filter(s -> s.stationId().equals("행당")).findFirst().orElseThrow();
        assertNull(haengdang.lat());
        assertNull(haengdang.lng());
    }

    @Test
    @DisplayName("노선은 구간·환승에 등장한 subwayId 를 모두 포함하고 표시 이름을 붙인다")
    void collectsLines() {
        SubwayGraph g = builder.build(segments, transfers, coords);

        assertEquals(Set.of("1002", "1005", "1075"), g.lines().stream().map(LineRow::lineId).collect(java.util.stream.Collectors.toSet()));
        assertTrue(g.lines().stream().anyMatch(l -> l.lineId().equals("1002") && l.name().equals("2호선")));
    }

    @Test
    @DisplayName("구간 하나는 양방향 SUBWAY 엣지 두 개가 되고 route_id 는 line_id 다")
    void edgesAreBidirectional() {
        SubwayGraph g = builder.build(segments, transfers, coords);

        assertEquals(6, g.edges().size());
        assertTrue(g.edges().stream().anyMatch(e -> e.fromNode().equals("왕십리") && e.toNode().equals("상왕십리") && e.routeId().equals("1002")));
        assertTrue(g.edges().stream().allMatch(e -> e.mode().equals("SUBWAY")));
    }

    @Test
    @DisplayName("환승은 station_id 로 매핑되고 source 는 extract 다")
    void transfersMapped() {
        SubwayGraph g = builder.build(segments, transfers, coords);

        assertEquals(3, g.transfers().size());
        TransferMetaRow t = g.transfers().get(0);
        assertEquals("왕십리", t.stationId());
        assertEquals("extract", t.source());
    }

    @Test
    @DisplayName("동명이역은 ID 표의 (역명, 노선) 행으로 별도 station_id 를 받는다 — 2호선 신촌과 경의중앙선 신촌")
    void disambiguatesSameNameStations() {
        SubwayGraphBuilder b = new SubwayGraphBuilder(StationIdTable.from(List.of(
                Map.of("station_id", "홍대입구", "name", "홍대입구", "codes", "1002:", "source", "timetable"),
                Map.of("station_id", "신촌", "name", "신촌", "codes", "1002:", "source", "timetable"),
                Map.of("station_id", "가좌", "name", "가좌", "codes", "1063:", "source", "assigned"),
                Map.of("station_id", "신촌_경의중앙", "name", "신촌", "codes", "1063:", "source", "assigned"))));
        List<Segment> segs = List.of(
                new Segment("1002", "홍대입구", "신촌", 90, 1000, "timetable"),
                new Segment("1063", "가좌", "신촌", 120, 1500, "avg"));

        SubwayGraph g = b.build(segs, List.of(), List.of());

        Set<String> ids = g.stations().stream().map(StationRow::stationId).collect(java.util.stream.Collectors.toSet());
        assertEquals(Set.of("홍대입구", "신촌", "가좌", "신촌_경의중앙"), ids);
        assertTrue(g.edges().stream().anyMatch(e -> e.fromNode().equals("가좌") && e.toNode().equals("신촌_경의중앙")));
    }
}
