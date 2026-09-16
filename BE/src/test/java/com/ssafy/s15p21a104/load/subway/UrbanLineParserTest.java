package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 국토교통부 "도시철도 전체노선"(공공데이터포털 15122916) → 노선별 역 목록.
 * 순번은 지선에서 중복돼(경의중앙 21 수색·신촌) 인접 관계에는 쓰지 않고, KTDB 링크가 만든 역 집합과 대조하는 데만 쓴다.
 */
class UrbanLineParserTest {

    private static Map<String, String> row(String region, String operator, String line, String seq, String name) {
        return Map.of("권역", "01", "권역명", region, "철도운영기관명", operator, "노선명", line, "순번", seq, "역명", name);
    }

    private final UrbanLineParser parser = new UrbanLineParser(new StationNameNormalizer(Map.of("서울역", "서울")));

    @Test
    @DisplayName("수도권 행만, 노선명 → line_id (공항 → 1065, 경의중앙 → 1063, 서해선 → 1093), 역명은 정규화(부기 제거·별칭)")
    void mapsLinesAndNormalizesNames() {
        Map<String, List<String>> out = parser.parse(List.of(
                row("수도권", "공항철도주식회사", "공항", "1", "서울역"),
                row("수도권", "공항철도주식회사", "공항", "2", "공덕"),
                row("수도권", "코레일", "경의중앙", "51", "아신(아세아연합신학대)"),
                row("수도권", "서해철도주식회사", "서해선", "1", "소사"),
                row("수도권", "코레일", "서해선", "20", "김포공항역"),
                row("부산권", "부산교통공사", "1호선", "1", "노포")));

        assertEquals(List.of("서울", "공덕"), out.get("1065"));
        assertEquals(List.of("아신"), out.get("1063"));
        assertEquals(List.of("소사", "김포공항"), out.get("1093"));
        assertFalse(out.containsKey("1001"));
    }

    @Test
    @DisplayName("순번이 중복된 지선 역도 목록에 남는다 — 21 수색·신촌 둘 다. 같은 역이 두 번 나오면 하나로")
    void keepsBranchStationsAndDeduplicates() {
        Map<String, List<String>> out = parser.parse(List.of(
                row("수도권", "코레일", "경의중앙", "21", "수색"),
                row("수도권", "코레일", "경의중앙", "21", "신촌"),
                row("수도권", "코레일", "경의중앙", "22", "디지털미디어시티"),
                row("수도권", "코레일", "경의중앙", "22", "서울역"),
                row("수도권", "코레일", "경의중앙", "23", "가좌"),
                row("수도권", "코레일", "경의중앙", "23", "가좌")));

        assertEquals(List.of("수색", "신촌", "디지털미디어시티", "서울", "가좌"), out.get("1063"));
    }

    @Test
    @DisplayName("line_id 가 없는 노선(인천1호선·에버라인 등)은 건너뛰고 한 줄로 집계 경고한다")
    void unknownLinesAreSkippedWithOneWarning() {
        Map<String, List<String>> out = parser.parse(List.of(
                row("수도권", "인천교통공사", "인천1호선", "1", "계양"),
                row("수도권", "인천교통공사", "인천1호선", "2", "귤현"),
                row("수도권", "용인경량전철주식회사", "에버라인", "1", "기흥(백남준아트센터)"),
                row("수도권", "네오트랜스주식회사", "신분당", "1", "신사")));

        assertEquals(Map.of("1077", List.of("신사")), out);
        assertEquals(1, parser.warnings().size());
        assertTrue(parser.warnings().get(0).contains("인천1호선"));
        assertTrue(parser.warnings().get(0).contains("에버라인"));
    }
}
