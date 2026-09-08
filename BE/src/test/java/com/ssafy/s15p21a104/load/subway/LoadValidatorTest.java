package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** 스키마가 강제하지 않는 모드-노드 규칙과 값 범위를 적재 전에 검증한다. 오류가 있으면 적재하지 않는다. */
class LoadValidatorTest {

    private static SubwayGraph graph(List<StationRow> stations, List<EdgeRow> edges) {
        return new SubwayGraph(
                List.of(new LineRow("1001", "1호선")),
                stations,
                List.of(),
                edges);
    }

    private final StationRow seoul = new StationRow("서울", "서울", 37.5531, 126.9725, Set.of("1001"));
    private final StationRow cityHall = new StationRow("시청", "시청", 37.5636, 126.9754, Set.of("1001"));

    @Test
    @DisplayName("정상 그래프는 오류가 없다")
    void validGraphHasNoErrors() {
        ValidationReport r = LoadValidator.validate(graph(List.of(seoul, cityHall),
                List.of(new EdgeRow("서울", "시청", "SUBWAY", "1001", 120, "timetable"))));

        assertTrue(r.errors().isEmpty(), r.errors().toString());
    }

    @Test
    @DisplayName("출발과 도착이 같은 엣지는 오류")
    void selfLoopIsError() {
        ValidationReport r = LoadValidator.validate(graph(List.of(seoul),
                List.of(new EdgeRow("서울", "서울", "SUBWAY", "1001", 120, "timetable"))));

        assertEquals(1, r.errors().size());
    }

    @Test
    @DisplayName("이동 초가 0 이하면 오류")
    void nonPositiveTravelIsError() {
        ValidationReport r = LoadValidator.validate(graph(List.of(seoul, cityHall),
                List.of(new EdgeRow("서울", "시청", "SUBWAY", "1001", 0, "timetable"))));

        assertEquals(1, r.errors().size());
    }

    @Test
    @DisplayName("존재하지 않는 역을 가리키는 엣지는 오류")
    void unknownStationIsError() {
        ValidationReport r = LoadValidator.validate(graph(List.of(seoul),
                List.of(new EdgeRow("서울", "종각", "SUBWAY", "1001", 120, "timetable"))));

        assertEquals(1, r.errors().size());
        assertTrue(r.errors().get(0).contains("종각"));
    }

    @Test
    @DisplayName("적재되지 않은 노선을 route_id 로 쓰는 엣지는 오류")
    void unknownLineIsError() {
        ValidationReport r = LoadValidator.validate(graph(List.of(seoul, cityHall),
                List.of(new EdgeRow("서울", "시청", "SUBWAY", "1009", 120, "timetable"))));

        assertEquals(1, r.errors().size());
    }

    @Test
    @DisplayName("한 노선의 엣지가 서로 이어지지 않으면(연결 요소 2개 이상) 경고 — 원천 구간 누락을 드러낸다")
    void disconnectedLineIsWarning() {
        StationRow a = new StationRow("가", "가", 37.50, 127.00, Set.of("1001"));
        StationRow b = new StationRow("나", "나", 37.51, 127.01, Set.of("1001"));
        StationRow c = new StationRow("다", "다", 37.52, 127.02, Set.of("1001"));
        StationRow d = new StationRow("라", "라", 37.53, 127.03, Set.of("1001"));

        ValidationReport r = LoadValidator.validate(graph(List.of(a, b, c, d), List.of(
                new EdgeRow("가", "나", "SUBWAY", "1001", 60, "avg"),
                new EdgeRow("나", "가", "SUBWAY", "1001", 60, "avg"),
                new EdgeRow("다", "라", "SUBWAY", "1001", 60, "avg"),
                new EdgeRow("라", "다", "SUBWAY", "1001", 60, "avg"))));

        assertTrue(r.errors().isEmpty());
        assertEquals(1, r.warnings().size());
        assertTrue(r.warnings().get(0).contains("1001"));
        assertTrue(r.warnings().get(0).contains("2"));
    }

    @Test
    @DisplayName("수도권 밖 좌표는 오류, 좌표 없음은 경고")
    void coordinateRangeAndMissing() {
        StationRow far = new StationRow("부산", "부산", 35.1, 129.0, Set.of("1001"));
        StationRow noCoord = new StationRow("행당", "행당", null, null, Set.of("1001"));

        ValidationReport r = LoadValidator.validate(graph(List.of(far, noCoord), List.of()));

        assertEquals(1, r.errors().size());
        assertEquals(1, r.warnings().size());
        assertTrue(r.warnings().get(0).contains("행당"));
    }
}
