package com.ssafy.s15p21a104.load.bus;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * "버스노선별 정류소 정보"(OA-1095, 노선 × 경유 정류소 41,688행) → bus_route 행 (ROUTE_ID distinct 718).
 * 경유 순번은 V1 에 테이블이 없어 여기서 쓰지 않는다.
 */
class BusRouteParserTest {

    private static Map<String, String> row(String routeId, String routeName, String seq, String nodeId) {
        return Map.of("ROUTE_ID", routeId, "노선명", routeName, "순번", seq, "NODE_ID", nodeId, "ARS_ID", "11486",
                "정류소명", "월계동진아교통", "X좌표", "127.06447", "Y좌표", "37.627618");
    }

    private final BusRouteParser parser = new BusRouteParser();

    @Test
    @DisplayName("ROUTE_ID 별로 한 행만 만들고 노선명은 첫 행 값을 쓴다")
    void distinctByRouteId() {
        List<BusRouteRow> out = parser.parse(List.of(
                row("100100026", "147", "1", "110000384"),
                row("100100026", "147", "2", "110000385"),
                row("100100148", "1132", "1", "110000384")));

        assertEquals(2, out.size());
        assertEquals("100100026", out.get(0).routeId());
        assertEquals("147", out.get(0).name());
        assertEquals("1132", out.get(1).name());
        assertTrue(parser.warnings().isEmpty());
    }

    @Test
    @DisplayName("같은 ROUTE_ID 에 다른 노선명이 섞이면 경고하고 첫 값을 유지한다")
    void conflictingNameWarns() {
        List<BusRouteRow> out = parser.parse(List.of(
                row("100100026", "147", "1", "110000384"),
                row("100100026", "147번", "2", "110000385")));

        assertEquals(1, out.size());
        assertEquals("147", out.get(0).name());
        assertEquals(1, parser.warnings().size());
    }

    @Test
    @DisplayName("ROUTE_ID 나 노선명이 비어 있는 행은 건너뛰고 경고한다")
    void blankIdOrNameSkipped() {
        List<BusRouteRow> out = parser.parse(List.of(
                row("", "147", "1", "110000384"),
                row("100100150", " ", "1", "110000384")));

        assertTrue(out.isEmpty());
        assertEquals(2, parser.warnings().size());
    }

    @Test
    @DisplayName("노선명 양쪽 공백을 없앤다")
    void trimsName() {
        List<BusRouteRow> out = parser.parse(List.of(row("100100026", " 147 ", "1", "110000384")));

        assertEquals("147", out.get(0).name());
    }
}
