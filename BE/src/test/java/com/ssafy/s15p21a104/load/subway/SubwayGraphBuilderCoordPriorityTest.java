package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 좌표 원천 우선순위는 목록 순서다: 서울교통공사 역사 좌표 → 국가철도공단 역위치(노선별) → KTDB 노드(이름만).
 * 같은 (노선, 역)이 앞 원천에 있으면 뒤 원천은 쓰지 않고, 노선 코드가 없는 KTDB 좌표는 이름 대조로만 쓰인다.
 */
class SubwayGraphBuilderCoordPriorityTest {

    private final SubwayGraphBuilder builder = new SubwayGraphBuilder(StationIdTable.identity());

    private final List<Segment> segments = List.of(
            new Segment("1001", "서울", "남영", 100, 1000, "timetable"),
            new Segment("1001", "남영", "용산", 100, 1000, "timetable"),
            new Segment("1007", "석남", "산곡", 100, 1000, "timetable"));

    @Test
    @DisplayName("서울교통공사 좌표가 있으면 국가철도공단·KTDB 좌표가 있어도 그것을 쓴다")
    void seoulMetroWinsOverOthers() {
        SubwayGraph g = builder.build(segments, List.of(), List.of(
                new StationCoord("1001", "서울", 37.5547, 126.9708, "150"),
                new StationCoord("1001", "서울", 37.5600, 126.9800, null),
                new StationCoord(null, "서울", 37.5700, 126.9900, null)));

        assertEquals(37.5547, station(g, "서울").lat(), 1e-9);
    }

    @Test
    @DisplayName("서울교통공사에 없는 역은 국가철도공단 좌표를 쓴다 — 남영·용산")
    void kricFillsGaps() {
        SubwayGraph g = builder.build(segments, List.of(), List.of(
                new StationCoord("1001", "남영", 37.5410, 126.9712, null),
                new StationCoord(null, "남영", 37.5403, 126.9712, null)));

        assertEquals(37.5410, station(g, "남영").lat(), 1e-9);
    }

    @Test
    @DisplayName("국가철도공단에도 없으면 KTDB 노드 좌표(노선 코드 없음)를 이름으로 대조해 쓴다 — 7호선 석남·산곡")
    void ktdbIsLastResort() {
        SubwayGraph g = builder.build(segments, List.of(), List.of(
                new StationCoord(null, "석남", 37.5080, 126.6760, null)));

        assertEquals(37.5080, station(g, "석남").lat(), 1e-9);
        assertEquals(null, station(g, "산곡").lat());
    }

    private static StationRow station(SubwayGraph g, String id) {
        return g.stations().stream().filter(s -> s.stationId().equals(id)).findFirst().orElseThrow();
    }
}
