package com.ssafy.s15p21a104.load.bus;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 열린데이터광장 "서울시 버스정류소 위치정보"(OA-15067) + "버스노선별 정류소 정보"(OA-1095) → bus_stop 행.
 * 위치정보 파일이 정본이고, 노선별 파일에만 있는 정류소(경기 구간 1,863개)는 그 파일의 좌표로 보충한다.
 */
class BusStopParserTest {

    private static Map<String, String> stop(String nodeId, String name, String x, String y) {
        return Map.of("NODE_ID", nodeId, "ARS_ID", "00001", "정류소명", name, "X좌표", x, "Y좌표", y, "정류소타입", "일반차로");
    }

    private static Map<String, String> routeStop(String routeId, String nodeId, String name, String x, String y) {
        return Map.of("ROUTE_ID", routeId, "노선명", "147", "순번", "1", "NODE_ID", nodeId, "ARS_ID", "11486",
                "정류소명", name, "X좌표", x, "Y좌표", y);
    }

    private static BusStopRow byId(List<BusStopRow> rows, String id) {
        return rows.stream().filter(r -> r.stopId().equals(id)).findFirst().orElseThrow();
    }

    private final BusStopParser parser = new BusStopParser();

    @Test
    @DisplayName("NODE_ID 를 stop_id 로 쓰고 X좌표를 경도·Y좌표를 위도로 읽는다")
    void mapsColumns() {
        List<BusStopRow> out = parser.parse(
                List.of(stop("123000689", "한강버스.잠실선착장", "127.084778", "37.518944")), List.of());

        assertEquals(1, out.size());
        BusStopRow s = out.get(0);
        assertEquals("123000689", s.stopId());
        assertEquals("한강버스.잠실선착장", s.name());
        assertEquals(37.518944, s.lat(), 1e-9);
        assertEquals(127.084778, s.lng(), 1e-9);
    }

    @Test
    @DisplayName("노선별 파일에만 있는 정류소는 그 파일 좌표로 한 번만 추가하고, 둘 다 있으면 위치정보 파일 값을 쓴다")
    void unionPrefersStopFile() {
        List<BusStopRow> out = parser.parse(
                List.of(stop("111000012", "구파발역입구", "126.9188", "37.6366")),
                List.of(routeStop("100100026", "111000012", "구파발역입구(노선파일)", "126.0", "37.0"),
                        routeStop("100100026", "227500083", "경기정류소", "127.1", "37.5"),
                        routeStop("100100148", "227500083", "경기정류소", "127.1", "37.5")));

        assertEquals(2, out.size());
        assertEquals("구파발역입구", byId(out, "111000012").name());
        assertEquals(37.6366, byId(out, "111000012").lat(), 1e-9);
        assertEquals(37.5, byId(out, "227500083").lat(), 1e-9);
        assertEquals(1, parser.addedFromRouteFile());
    }

    @Test
    @DisplayName("좌표가 비어 있으면 null 로 두고 경고를 남긴다 — 값을 만들어 넣지 않는다")
    void blankCoordsBecomeNull() {
        List<BusStopRow> out = parser.parse(List.of(stop("100000001", "좌표없음", "", "")), List.of());

        assertEquals(1, out.size());
        assertNull(out.get(0).lat());
        assertNull(out.get(0).lng());
        assertEquals(1, parser.warnings().size());
    }

    @Test
    @DisplayName("NODE_ID 나 정류소명이 비어 있는 행은 건너뛰고 경고를 남긴다")
    void blankIdOrNameSkipped() {
        List<BusStopRow> out = parser.parse(
                List.of(stop("", "이름만", "127.0", "37.5"), stop("100000002", "", "127.0", "37.5")), List.of());

        assertTrue(out.isEmpty());
        assertEquals(2, parser.warnings().size());
    }

    @Test
    @DisplayName("정류소명 양쪽 공백을 없앤다")
    void trimsName() {
        List<BusStopRow> out = parser.parse(List.of(stop("100000003", "  월계동진아교통 ", "127.06447", "37.627618")), List.of());

        assertEquals("월계동진아교통", out.get(0).name());
    }
}
