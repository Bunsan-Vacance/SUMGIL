package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 국가철도공단 노선별 "역위치" 파일(공공데이터포털 15041300 등 11종) → 역 좌표.
 * 열은 `철도운영기관(명) · 선명 · 역명 · 경도 · 위도`. 7호선 파일의 부천·인천 구간 11역은 0,0 이고 3호선 원흥은 위도에
 * 소수점이 빠져 있어(37650709) 무효 좌표는 건너뛰고 경고로 남긴다 — 값을 고쳐 넣지 않는다.
 */
class KricStationCoordParserTest {

    private static Map<String, String> row(String line, String name, String lng, String lat) {
        return Map.of("철도운영기관", "서울교통공사", "선명", line, "역명", name, "경도", lng, "위도", lat);
    }

    private final KricStationCoordParser parser = new KricStationCoordParser(new StationNameNormalizer(Map.of("서울역", "서울")));

    @Test
    @DisplayName("경도·위도 열을 lng·lat 로 읽고 선명을 line_id 로 바꾼다 — 1호선 → 1001")
    void mapsColumns() {
        List<StationCoord> out = parser.parse(List.of(row("1호선", "남영", "126.9712", "37.5410")));

        assertEquals(1, out.size());
        StationCoord c = out.get(0);
        assertEquals("1001", c.lineId());
        assertEquals("남영", c.stationName());
        assertEquals(37.5410, c.lat(), 1e-9);
        assertEquals(126.9712, c.lng(), 1e-9);
        assertNull(c.externalCode());
    }

    @Test
    @DisplayName("열 이름이 '철도운영기관명'인 파일(2·6·7호선)도 같은 규칙으로 읽는다")
    void acceptsHeaderVariant() {
        List<StationCoord> out = parser.parse(List.of(
                Map.of("철도운영기관명", "서울교통공사", "선명", "2호선", "역명", "강남", "경도", "127.0276", "위도", "37.4979")));

        assertEquals(1, out.size());
        assertEquals("1002", out.get(0).lineId());
    }

    @Test
    @DisplayName("'경의중앙'·'수인분당'처럼 '선'이 빠진 표기도 노선 코드로 바꾼다 — 1063·1075")
    void mapsLineNamesWithoutSuffix() {
        List<StationCoord> out = parser.parse(List.of(
                row("경의중앙", "응봉", "127.0344", "37.5500"),
                row("수인분당", "가천대", "127.1265", "37.4488"),
                row("9호선", "노들", "126.9530", "37.5128")));

        assertEquals(List.of("1063", "1075", "1009"), out.stream().map(StationCoord::lineId).toList());
    }

    @Test
    @DisplayName("모르는 선명은 line_id 없이(null) 좌표만 살리고 경고한다 — 이름으로는 여전히 쓸 수 있다")
    void unknownLineKeepsCoordWithoutLineId() {
        List<StationCoord> out = parser.parse(List.of(row("의정부경전철", "탑석", "127.0900", "37.7300")));

        assertEquals(1, out.size());
        assertNull(out.get(0).lineId());
        assertEquals(1, parser.warnings().size());
    }

    @Test
    @DisplayName("무효 좌표(0,0 · 소수점 빠진 값 · 빈 값 · 수도권 밖)는 건너뛰고 한 줄 집계 경고를 남긴다")
    void skipsInvalidCoordinatesWithAggregatedWarning() {
        List<StationCoord> out = parser.parse(List.of(
                row("7호선", "까치울", "0", "0"),
                row("3호선", "원흥", "126.873239", "37650709"),
                row("5호선", "방화", "", ""),
                row("1호선", "부산", "129.0403", "35.1150"),
                row("1호선", "남영", "126.9712", "37.5410")));

        assertEquals(1, out.size());
        assertEquals("남영", out.get(0).stationName());
        assertEquals(4, parser.skipped());
        assertEquals(1, parser.warnings().size());
        assertTrue(parser.warnings().get(0).contains("4") && parser.warnings().get(0).contains("까치울") && parser.warnings().get(0).contains("원흥"));
    }

    @Test
    @DisplayName("역명은 정규화기를 거친다 — 석남(거북시장) → 석남, 서울역 → 서울")
    void normalizesNames() {
        List<StationCoord> out = parser.parse(List.of(
                row("7호선", "석남(거북시장)", "126.6760", "37.5080"),
                row("1호선", "서울역", "126.9708", "37.5547")));

        assertEquals("석남", out.get(0).stationName());
        assertEquals("서울", out.get(1).stationName());
    }

    @Test
    @DisplayName("같은 (선, 역)이 두 번 나오면 좌표가 같으면 하나로 합치고, 다르면 첫 값을 쓰고 경고한다 — 5호선 파일은 전 행이 두 번 있다")
    void dedupesRepeatedRows() {
        List<StationCoord> out = parser.parse(List.of(
                row("5호선", "방화", "126.8127", "37.5777"),
                row("5호선", "방화", "126.8127", "37.5777"),
                row("5호선", "개화산", "126.8066", "37.5726"),
                row("5호선", "개화산", "126.8100", "37.5726")));

        assertEquals(2, out.size());
        assertEquals(126.8066, out.get(1).lng(), 1e-9);
        assertEquals(1, parser.warnings().size());
    }
}
