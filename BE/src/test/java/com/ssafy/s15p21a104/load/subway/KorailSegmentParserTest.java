package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 공공데이터포털 "서울시 도시철도 구간정보"(코레일 광역 구간). 거리만 있고 소요시간이 없어
 * 표정속도로 추정하고 source='avg' 로 표시한다. 정확한 시간표가 생기면 그 값이 덮어쓴다.
 */
class KorailSegmentParserTest {

    private static Map<String, String> row(String fromId, String from, String fromLine,
                                           String toId, String to, String toLine, String meters) {
        return Map.of("출발_역_ID", fromId, "출발_역_명칭", from, "출발_호선_내용", fromLine,
                "도착_역_ID", toId, "도착_역_명칭", to, "도착_호선_내용", toLine, "거리", meters);
    }

    private final KorailSegmentParser parser =
            new KorailSegmentParser(new StationNameNormalizer(Map.of()), 9.2);

    @Test
    @DisplayName("거리(m)를 표정속도 9.2 m/s 로 나눠 초를 추정한다 — 1,100 m ≈ 120 초")
    void estimatesTravelSecFromDistance() {
        List<Segment> out = parser.parse(List.of(row("1705", "관악", "101", "1706", "안양", "101", "1100")));

        assertEquals(1, out.size());
        Segment s = out.get(0);
        assertEquals("1001", s.lineId());
        assertEquals("관악", s.fromName());
        assertEquals("안양", s.toName());
        assertEquals(120, s.travelSec());
        assertEquals(1100, s.distanceM());
        assertEquals("avg", s.source());
    }

    @Test
    @DisplayName("괄호 부기가 붙은 역명을 정규화한다 — 이촌(국립중앙박물관) → 이촌")
    void normalizesNames() {
        List<Segment> out = parser.parse(List.of(row("1008", "이촌(국립중앙박물관)", "103", "1009", "서빙고", "103", "1600")));

        assertEquals("이촌", out.get(0).fromName());
        assertEquals("1063", out.get(0).lineId());
    }

    @Test
    @DisplayName("모르는 노선 코드는 건너뛰고 경고로 남긴다")
    void unknownLineCodeIsSkipped() {
        List<Segment> out = parser.parse(List.of(row("1", "가", "999", "2", "나", "999", "1000")));

        assertTrue(out.isEmpty());
        assertEquals(1, parser.warnings().size());
    }

    @Test
    @DisplayName("출발·도착 호선이 다르면 노선 경계 구간으로 보고 출발 호선을 쓴다")
    void mixedLineUsesDeparture() {
        List<Segment> out = parser.parse(List.of(row("1", "남태령", "4", "2", "선바위", "105", "1500")));

        assertEquals("1004", out.get(0).lineId());
    }

    @Test
    @DisplayName("소요시간은 최소 30초로 둔다 — 아주 짧은 구간이 0초가 되지 않게")
    void minimumThirtySeconds() {
        List<Segment> out = parser.parse(List.of(row("1", "가", "101", "2", "나", "101", "100")));

        assertEquals(30, out.get(0).travelSec());
    }
}
