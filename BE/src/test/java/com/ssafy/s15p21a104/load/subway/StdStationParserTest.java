package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 전국도시철도역사정보표준데이터(공공데이터포털 15013205) → 역 좌표(노선 코드 포함).
 * 국가철도공단 역위치 파일이 없는 노선(경춘·경강·서해·공항·신분당·우이신설·신림)의 좌표 원천이고, 역번호는 station-ids 표의 정본이다.
 */
class StdStationParserTest {

    private static Map<String, String> row(String no, String name, String lineCode, String lineName, String lat, String lng) {
        return Map.of("역번호", no, "역사명", name, "노선번호", lineCode, "노선명", lineName,
                "역위도", lat, "역경도", lng, "운영기관명", "한국철도공사");
    }

    private final StdStationParser parser = new StdStationParser(new StationNameNormalizer(Map.of("서울역", "서울")));

    @Test
    @DisplayName("노선번호 → line_id (I4108 경의중앙선 → 1063), 역명은 부기·끝의 '역' 제거, 역번호는 externalCode 로")
    void mapsCodeAndNormalizesName() {
        List<StationCoord> out = parser.parse(List.of(
                row("1014", "청량리역", "I4108", "경의중앙선", "37.580", "127.045"),
                row("A01", "서울", "I28A1", "인천국제공항선", "37.549", "126.970"),
                row("D004", "신사", "I11D1", "신분당선", "37.516", "127.020")));

        assertEquals(3, out.size());
        StationCoord c = out.get(0);
        assertEquals("1063", c.lineId());
        assertEquals("청량리", c.stationName());
        assertEquals(37.580, c.lat());
        assertEquals("1014", c.externalCode());
        assertEquals("1065", out.get(1).lineId());
        assertEquals("서울", out.get(1).stationName());
        assertEquals("1077", out.get(2).lineId());
    }

    @Test
    @DisplayName("서비스 노선이 여럿인 물리 선로 코드(I4102 경원선)는 line_id 없이(null) 이름으로만 쓴다")
    void ambiguousPhysicalLineHasNoLineId() {
        List<StationCoord> out = parser.parse(List.of(row("1009", "서빙고역", "I4102", "경원선", "37.519", "126.988")));

        assertNull(out.get(0).lineId());
        assertEquals("서빙고", out.get(0).stationName());
    }

    @Test
    @DisplayName("수도권 범위 밖(부산·대구)과 좌표가 비어 있는 행은 건너뛴다 — 전국 파일이라 동명역이 섞인다")
    void skipsOutsideMetroAndMissingCoords() {
        List<StationCoord> out = parser.parse(List.of(
                row("101", "중앙역", "S2601", "부산1호선", "35.104", "129.036"),
                row("1756", "중앙역", "I28K1", "수인선", "37.316", "126.839"),
                row("9999", "좌표없음", "I4108", "경의중앙선", "", "")));

        assertEquals(1, out.size());
        assertEquals("1075", out.get(0).lineId());
        assertEquals(2, parser.skipped());
    }

    @Test
    @DisplayName("같은 (노선, 역)이 두 번이면 첫 값을 쓴다")
    void deduplicates() {
        List<StationCoord> out = parser.parse(List.of(
                row("1014", "청량리역", "I4108", "경의중앙선", "37.580", "127.045"),
                row("1014", "청량리역", "I4108", "경의중앙선", "37.581", "127.046")));

        assertEquals(1, out.size());
        assertEquals(37.580, out.get(0).lat());
    }
}
