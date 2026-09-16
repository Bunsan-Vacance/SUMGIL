package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * KTDB 철도망 노드(data/railgeometry/ktdb-rail-node_2024.csv, 전국 1,652개) → 이름별 역 좌표.
 * 국가철도공단 파일에 좌표가 없거나 무효인 역(7호선 부천·인천 11역, 3호선 원흥)의 마지막 보완 원천이다.
 * 선로 노드라 역 하나에 노드가 2개(승강장·방향별)일 수 있어 평균점을 쓰고, 전국 데이터라 수도권 범위 밖 동명 노드는 걸러낸다.
 */
class KtdbNodeCoordParserTest {

    private static Map<String, String> node(String id, String lat, String lng, String name) {
        return Map.of("node_id", id, "lat", lat, "lng", lng, "station_name_raw", name);
    }

    private final KtdbNodeCoordParser parser = new KtdbNodeCoordParser(new StationNameNormalizer(Map.of("서울역", "서울")));

    @Test
    @DisplayName("이름 하나에 노드 하나면 그 좌표, 노선 코드는 없다(null) — 이름으로만 대조하는 보완 원천")
    void singleNode() {
        List<StationCoord> out = parser.parse(List.of(node("1", "37.54032", "126.97124", "남영역")));

        assertEquals(1, out.size());
        assertNull(out.get(0).lineId());
        assertEquals("남영", out.get(0).stationName());
        assertEquals(37.54032, out.get(0).lat(), 1e-9);
    }

    @Test
    @DisplayName("같은 이름 노드가 여러 개면 평균점 — 구로 두 노드 30 m 차이")
    void averagesMultipleNodes() {
        List<StationCoord> out = parser.parse(List.of(
                node("1", "37.50239", "126.88150", "구로역"),
                node("2", "37.50260", "126.88120", "구로역")));

        assertEquals(1, out.size());
        assertEquals(37.502495, out.get(0).lat(), 1e-9);
        assertEquals(126.88135, out.get(0).lng(), 1e-9);
    }

    @Test
    @DisplayName("수도권 범위 밖 노드는 제외한다 — 전국 파일이라 부산·여수의 동명역이 섞인다")
    void dropsNodesOutsideMetroArea() {
        List<StationCoord> out = parser.parse(List.of(
                node("1", "34.75393973", "127.74899261", "여수엑스포역(고속)"),
                node("2", "35.1150", "129.0403", "부산역"),
                node("3", "37.5547", "126.9708", "서울역")));

        assertEquals(1, out.size());
        assertEquals("서울", out.get(0).stationName());
    }

    @Test
    @DisplayName("이름 정규화: 괄호 부기와 끝의 '역'을 떼고 별칭을 적용한다 — 석남(거북시장)역 → 석남, 역촌역 → 역촌")
    void normalizesNames() {
        List<StationCoord> out = parser.parse(List.of(
                node("1", "37.5080", "126.6760", "석남(거북시장)역"),
                node("2", "37.6060", "126.9227", "역촌역")));

        assertEquals(List.of("석남", "역촌"), out.stream().map(StationCoord::stationName).toList());
    }

    @Test
    @DisplayName("이름이 비어 있거나 좌표가 숫자가 아닌 노드는 무시한다")
    void ignoresBlankOrBrokenNodes() {
        List<StationCoord> out = parser.parse(List.of(
                node("1", "37.5", "127.0", ""),
                node("2", "x", "127.0", "가"),
                node("3", "37.5", "127.0", "나")));

        assertEquals(1, out.size());
        assertTrue(parser.warnings().isEmpty());
    }
}
