package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * KTDB 철도망 링크(data/railgeometry/ktdb-rail-link_2024.csv) → 시각표가 없는 노선의 거리 기반 구간.
 * 링크 하나가 인접 역 한 쌍이고 length_km 가 선로 거리다. 노드 이름은 "판교역(신분당)" 꼴이라 괄호와 끝의 '역'을 뗀다.
 * 소요시간은 노선별 표정속도(conf/line-speeds.csv)로 추정하고 source='avg' 로 표시한다.
 */
class KtdbLinkSegmentParserTest {

    private static Map<String, String> node(String id, String name) {
        return Map.of("node_id", id, "lat", "37.5", "lng", "127.0", "station_name_raw", name);
    }

    private static Map<String, String> link(String from, String to, String lineName, String physical, String km) {
        return Map.of("link_id", from + to, "from_node_id", from, "to_node_id", to,
                "line_name_raw", lineName, "physical_line_name_raw", physical, "length_km", km);
    }

    private final StationNameNormalizer normalizer = new StationNameNormalizer(Map.of("서울역", "서울"));
    private final LineSpeeds speeds = LineSpeeds.from(List.of(
            Map.of("line_id", "1077", "mps", "14.0"),
            Map.of("line_id", "1063", "mps", "9.9")), 9.2);

    private KtdbLinkSegmentParser parser() {
        return new KtdbLinkSegmentParser(normalizer, speeds, Map.of());
    }

    @Test
    @DisplayName("링크 하나 = 인접 역 한 쌍. 이름은 괄호·'역'을 떼고, 거리(km)를 m 로, 소요는 노선 표정속도로 — 판교~정자 3.1 km / 14.0 m/s ≈ 221초")
    void linkBecomesSegment() {
        List<Segment> out = parser().parse(
                List.of(node("1", "판교역(신분당)"), node("2", "정자역(신분당)")),
                List.of(link("1", "2", "신분당선", "신분당선", "3.1")), Set.of());

        assertEquals(1, out.size());
        Segment s = out.get(0);
        assertEquals("1077", s.lineId());
        assertEquals("판교", s.fromName());
        assertEquals("정자", s.toName());
        assertEquals(3100, s.distanceM());
        assertEquals(221, s.travelSec());
        assertEquals("avg", s.source());
    }

    @Test
    @DisplayName("분기 노드는 역이 아니다 — 같은 노선의 앞뒤 링크를 이어 거리를 합친다 (한국항공대→분기→수색 1.7+1.7 = 3.4 km)")
    void junctionNodesAreContracted() {
        List<Segment> out = parser().parse(
                List.of(node("1", "한국항공대"), node("9", "분기(수색직결선_경의)"), node("2", "수색")),
                List.of(link("1", "9", "경의중앙선(수도권전철)", "경의선", "1.7"),
                        link("9", "2", "경의중앙선(수도권전철)", "경의선", "1.7")), Set.of());

        assertEquals(1, out.size());
        assertEquals("1063", out.get(0).lineId());
        assertEquals(Set.of("한국항공대", "수색"), Set.of(out.get(0).fromName(), out.get(0).toName()));
        assertEquals(3400, out.get(0).distanceM());
        assertTrue(parser().warnings().isEmpty());
    }

    @Test
    @DisplayName("분기 노드에 링크가 셋 이상 걸리면 어느 쪽을 이을지 알 수 없다 — 그 링크들은 버리고 경고")
    void junctionWithThreeNeighborsIsDroppedWithWarning() {
        var p = parser();
        List<Segment> out = p.parse(
                List.of(node("1", "가"), node("2", "나"), node("3", "다"), node("9", "분기(삼각선)")),
                List.of(link("1", "9", "신분당선", "", "1"), link("9", "2", "신분당선", "", "1"), link("9", "3", "신분당선", "", "1")), Set.of());

        assertTrue(out.isEmpty());
        assertEquals(1, p.warnings().size());
        assertTrue(p.warnings().get(0).contains("분기"));
    }

    @Test
    @DisplayName("서비스 노선명이 비어 있는 물리 링크는 예외 표로 노선을 붙인다 — 경춘선 광운대 지선(망우선 4.3 km)")
    void emptyLineNameUsesOverrides() {
        var p = new KtdbLinkSegmentParser(normalizer, speeds,
                Map.of("상봉|광운대", new KtdbLinkSegmentParser.LinkOverride(List.of("1067"), null)));
        List<Segment> out = p.parse(
                List.of(node("1", "상봉역(경춘)"), node("2", "광운대역(경춘)")),
                List.of(link("1", "2", "", "망우선", "4.3")), Set.of());

        assertEquals(1, out.size());
        assertEquals("1067", out.get(0).lineId());
        assertEquals(4300, out.get(0).distanceM());
        assertEquals(467, out.get(0).travelSec()); // 표에 없는 노선은 기본 9.2 m/s
    }

    @Test
    @DisplayName("KTDB 에 링크가 없는 구간은 예외 표의 거리로 만든다 — 경의선 가좌~신촌 2.7 km. 링크가 이미 있으면 KTDB 값을 두고 경고")
    void missingLinkIsAddedFromOverrides() {
        var p = new KtdbLinkSegmentParser(normalizer, speeds, Map.of(
                "가좌|신촌", new KtdbLinkSegmentParser.LinkOverride(List.of("1063"), 2700),
                "신촌|서울", new KtdbLinkSegmentParser.LinkOverride(List.of("1063"), 9999)));
        List<Segment> out = p.parse(
                List.of(node("1", "가좌"), node("2", "신촌(경의)"), node("3", "서울역(경의)")),
                List.of(link("2", "3", "경의중앙선(수도권전철)", "경의선", "3.1")), Set.of());

        assertEquals(2, out.size());
        Segment added = out.stream().filter(s -> s.fromName().equals("가좌")).findFirst().orElseThrow();
        assertEquals("신촌", added.toName());
        assertEquals(2700, added.distanceM());
        assertEquals(273, added.travelSec()); // 2700 / 9.9
        Segment kept = out.stream().filter(s -> s.toName().equals("서울")).findFirst().orElseThrow();
        assertEquals(3100, kept.distanceM());
        assertEquals(1, p.warnings().size());
        assertTrue(p.warnings().get(0).contains("9999"));
    }

    @Test
    @DisplayName("대상 노선 집합이 있으면 그 노선만, 비어 있으면 코드가 있는 노선 전부. 수도권 밖 노선(부산1호선)은 조용히 건너뛴다")
    void filtersByRequestedLines() {
        List<Map<String, String>> nodes = List.of(node("1", "가"), node("2", "나"), node("3", "다"), node("4", "라"));
        List<Map<String, String>> links = List.of(
                link("1", "2", "신분당선", "", "1"),
                link("2", "3", "서울2호선", "", "1"),
                link("3", "4", "부산1호선", "", "1"));

        List<Segment> only = parser().parse(nodes, links, Set.of("1077"));
        assertEquals(List.of("1077"), only.stream().map(Segment::lineId).toList());

        List<Segment> all = parser().parse(nodes, links, Set.of());
        assertEquals(Set.of("1077", "1002"), Set.of(all.get(0).lineId(), all.get(1).lineId()));
        assertEquals(2, all.size());
    }

    @Test
    @DisplayName("같은 (노선, 역 쌍) 링크가 둘이면 하나만 — 중랑~상봉이 상봉역(경춘)·상봉역(일반) 두 노드로 있다. 거리가 100 m 넘게 다르면 경고")
    void duplicatePairsCollapse() {
        var p = parser();
        List<Segment> out = p.parse(
                List.of(node("1", "중랑역(경춘)"), node("2", "상봉역(경춘)"), node("3", "상봉역(일반)"), node("4", "망우역(경춘)")),
                List.of(link("1", "2", "경춘선(수도권전철)", "", "0.8"),
                        link("1", "3", "경춘선(수도권전철)", "", "0.8"),
                        link("2", "4", "경춘선(수도권전철)", "", "0.6"),
                        link("3", "4", "경춘선(수도권전철)", "", "0.9")), Set.of());

        assertEquals(2, out.size());
        assertEquals(1, p.warnings().size());
        assertTrue(p.warnings().get(0).contains("상봉"));
    }

    @Test
    @DisplayName("소요시간은 최소 30초, 출발=도착·거리 없음·0 이하인 링크는 건너뛰고 경고")
    void guardsAgainstBadLinks() {
        var p = parser();
        List<Segment> out = p.parse(
                List.of(node("1", "가"), node("2", "나"), node("3", "다")),
                List.of(link("1", "2", "신분당선", "", "0.1"),
                        link("1", "1", "신분당선", "", "1"),
                        link("2", "3", "신분당선", "", "")), Set.of());

        assertEquals(1, out.size());
        assertEquals(30, out.get(0).travelSec());
        assertEquals(2, p.warnings().size());
    }

    @Test
    @DisplayName("파싱 뒤 노선별 역 집합을 돌려준다 — 전체노선 파일과 대조하는 데 쓴다")
    void exposesStationsByLine() {
        var p = parser();
        p.parse(List.of(node("1", "판교역(신분당)"), node("2", "정자역(신분당)")),
                List.of(link("1", "2", "신분당선", "", "3.1")), Set.of());

        assertEquals(Map.of("1077", Set.of("판교", "정자")), p.stationsByLine());
    }
}
