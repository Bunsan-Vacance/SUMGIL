package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * TAGO 역별 시각표(공공데이터포털 15098554) → 시각표 밖 노선의 슬롯별 대기.
 * 행 1개 = 역 1개에서 행선지로 떠나는 열차 1대의 출발 시각. 행선지가 어느 이웃 너머인지로 방향 엣지를 정한다.
 *
 * <pre>
 *   A — B — C — D        (본선)
 *       |
 *       E                (B 에서 갈라지는 지선)
 * </pre>
 */
class TagoTimetableParserTest {

    private static final String L = "1063";

    private static Map<String, String> row(String station, String daily, String upDown, String terminal, String dep) {
        Map<String, String> m = new HashMap<>();
        m.put("line_id", L);
        m.put("station_id", "1");
        m.put("station_name", station);
        m.put("tago_station_id", "MTRX");
        m.put("daily_type", daily);
        m.put("up_down", upDown);
        m.put("end_station_nm", terminal);
        m.put("dep_time", dep);
        m.put("arr_time", "0");
        return m;
    }

    private static final List<Segment> SEGMENTS = List.of(
            new Segment(L, "A", "B", 120, 1500, "avg"),
            new Segment(L, "B", "C", 120, 1500, "avg"),
            new Segment(L, "C", "D", 120, 1500, "avg"),
            new Segment(L, "B", "E", 120, 1500, "avg"));

    private final TagoTimetableParser parser = new TagoTimetableParser(new StationNameNormalizer(Map.of()));

    private static int[] waits(SlotWaits w, int dow) {
        int[] out = new int[SlotWaits.SLOTS];
        for (int s = 0; s < SlotWaits.SLOTS; s++) {
            out[s] = w.wait(dow, s);
        }
        return out;
    }

    @Test
    @DisplayName("행선지가 어느 이웃 너머인지로 방향 엣지를 정한다 — 분기역 B 에서 D 행은 B→C, E 행은 B→E, A 행은 B→A")
    void assignsDirectionByTerminalSide() {
        TagoTimetableParser.Result r = parser.parse(List.of(
                row("B", "01", "U", "D", "080000"),
                row("B", "01", "U", "E", "080500"),
                row("B", "01", "D", "A", "081000")), SEGMENTS);

        assertEquals(Set.of(L + "|B|C", L + "|B|E", L + "|B|A"), r.slotWaits().keySet());
        assertEquals(3, r.stats().used());
        assertEquals(0, r.stats().dropped());
        // B→E 는 평일 08:05 한 대뿐 — SlotWaits 정의 그대로 (토·일은 운행 없음 = NO_SERVICE)
        SlotWaits expected = SlotWaits.fromDepartures(List.of(List.of(29100), List.of(), List.of()));
        assertArrayEquals(waits(expected, 0), waits(r.slotWaits().get(L + "|B|E"), 0));
        assertEquals(SlotWaits.NO_SERVICE, r.slotWaits().get(L + "|B|E").wait(1, 16));
    }

    @Test
    @DisplayName("종점역(이웃 하나)의 출발은 그 이웃 방향이고, 행선지가 자기 자신인 행(종착 열차)과 출발 시각 '0' 행은 건너뛴다")
    void terminusAndArrivalRowsAreSkipped() {
        TagoTimetableParser.Result r = parser.parse(List.of(
                row("A", "01", "U", "D", "050000"),
                row("A", "01", "D", "A", "233000"),   // A 에 도착해 끝나는 열차
                row("D", "01", "D", "A", "0"),        // 출발 시각 없음
                row("D", "01", "D", "A", "")), SEGMENTS);

        assertEquals(Set.of(L + "|A|B"), r.slotWaits().keySet());
        assertEquals(1, r.stats().used());
        assertEquals(1, r.stats().terminalHere());
        assertEquals(2, r.stats().noDeparture());
    }

    @Test
    @DisplayName("행선지를 노선 역 목록에서 못 찾으면 같은 역·같은 U/D 의 다수결 이웃을 쓰고, 다수결도 없으면 버리고 경고한다")
    void unknownTerminalFallsBackToUpDownMajority() {
        TagoTimetableParser.Result r = parser.parse(List.of(
                row("B", "01", "U", "D", "080000"),
                row("B", "01", "U", "D", "081000"),
                row("B", "01", "U", "지평", "082000"),    // 노선 밖 이름 — U 는 C 쪽이 다수라 B→C
                row("B", "01", "D", "문산", "083000")),   // D 방향은 풀린 행이 없어 버림
                SEGMENTS);

        int[] bc = waits(r.slotWaits().get(L + "|B|C"), 0);
        int[] expected = waits(SlotWaits.fromDepartures(List.of(List.of(28800, 29400, 30000), List.of(), List.of())), 0);
        assertArrayEquals(expected, bc);
        assertEquals(2, r.stats().unresolvedTerminal());
        assertEquals(1, r.stats().fallbackUpDown());
        assertEquals(1, r.stats().dropped());
        assertTrue(parser.warnings().stream().anyMatch(w -> w.contains("문산")), parser.warnings().toString());
    }

    @Test
    @DisplayName("요일 코드 01·02·03 은 평일·토·일 슬롯으로 갈리고, 모르는 코드·노선·역은 버리고 센다")
    void dowAndUnknownRows() {
        TagoTimetableParser.Result r = parser.parse(List.of(
                row("A", "01", "U", "D", "060000"),
                row("A", "02", "U", "D", "070000"),
                row("A", "03", "U", "D", "080000"),
                row("A", "09", "U", "D", "090000"),
                row("Z", "01", "U", "D", "090000")), SEGMENTS);

        SlotWaits w = r.slotWaits().get(L + "|A|B");
        assertEquals(SlotWaits.fromDepartures(List.of(List.of(21600), List.of(), List.of())).wait(0, 10), w.wait(0, 10));
        assertEquals(SlotWaits.fromDepartures(List.of(List.of(), List.of(25200), List.of())).wait(1, 12), w.wait(1, 12));
        assertEquals(SlotWaits.fromDepartures(List.of(List.of(), List.of(), List.of(28800))).wait(2, 14), w.wait(2, 14));
        assertEquals(2, r.stats().dropped());
        assertFalse(parser.warnings().isEmpty());
        assertEquals(8, r.stats().edgesTotal());
        assertEquals(1, r.stats().edgesCovered());
    }

    @Test
    @DisplayName("행선지가 빈 행은 노선 전체의 U/D → 종점 다수결이나 반대 U/D 의 나머지 이웃으로 방향을 정한다 — 서해선은 역마다 한쪽 방향의 행선지가 비어 온다")
    void blankTerminalUsesLineLevelDirection() {
        // 선형 노선 A-B-C-D. B 에서는 D 행선지(U)만, C 에서는 A 행선지(D)만 행선지가 있고 반대 방향은 비어 온다.
        List<Segment> line = List.of(
                new Segment(L, "A", "B", 120, 1500, "avg"),
                new Segment(L, "B", "C", 120, 1500, "avg"),
                new Segment(L, "C", "D", 120, 1500, "avg"));
        TagoTimetableParser.Result r = parser.parse(List.of(
                row("B", "01", "U", "D", "080000"),
                row("B", "01", "D", "", "080500"),    // B 의 D 는 풀린 행이 없다 → 노선 전체 D 종점(A) 으로 → B→A
                row("C", "01", "D", "A", "081000"),
                row("C", "01", "U", "", "081500")),   // C 의 U → 노선 전체 U 종점(D) 으로 → C→D
                line);

        assertEquals(Set.of(L + "|B|C", L + "|B|A", L + "|C|B", L + "|C|D"), r.slotWaits().keySet());
        assertEquals(2, r.stats().fallbackUpDown());
        assertEquals(0, r.stats().dropped());

        // 노선 전체 다수결도 없을 때 — 이웃 둘인 역에서 반대 U/D 가 한 이웃으로 풀렸으면 나머지 이웃
        TagoTimetableParser.Result r2 = parser.parse(List.of(
                row("B", "01", "U", "D", "080000"),
                row("B", "01", "D", "", "080500")), line);
        assertEquals(Set.of(L + "|B|C", L + "|B|A"), r2.slotWaits().keySet());
        assertEquals(1, r2.stats().fallbackUpDown());
    }

    @Test
    @DisplayName("토요일(02) 행이 하나도 없는 노선은 휴일(03) 시각표를 토요일에도 쓴다 — TAGO 가 코레일·사철 토·일을 03 으로 합쳐 준다")
    void saturdayFallsBackToHolidayWhenLineHasNoSaturdayRows() {
        TagoTimetableParser.Result r = parser.parse(List.of(
                row("A", "01", "U", "D", "060000"),
                row("A", "03", "U", "D", "080000")), SEGMENTS);

        SlotWaits w = r.slotWaits().get(L + "|A|B");
        assertEquals(w.wait(2, 16), w.wait(1, 16));
        assertEquals(SlotWaits.fromDepartures(List.of(List.of(), List.of(), List.of(28800))).wait(2, 16), w.wait(1, 16));
        assertEquals(Set.of(L), r.stats().saturdayFromHoliday());
        assertTrue(parser.warnings().stream().anyMatch(s -> s.contains("토요일")));

        // 02 행이 하나라도 있는 노선은 그대로 — 우이신설처럼 토·일을 따로 주는 경우
        TagoTimetableParser.Result r2 = parser.parse(List.of(
                row("A", "02", "U", "D", "070000"),
                row("A", "03", "U", "D", "080000")), SEGMENTS);
        assertEquals(Set.of(), r2.stats().saturdayFromHoliday());
        assertEquals(SlotWaits.fromDepartures(List.of(List.of(), List.of(25200), List.of())).wait(1, 14), r2.slotWaits().get(L + "|A|B").wait(1, 14));
    }

    @Test
    @DisplayName("HHmmss 파싱 — 앞 0 생략·자정 넘김(00xxxx)은 그대로 초로, '0'·빈 값·형식 밖은 -1")
    void parsesHms() {
        assertEquals(23 * 3600 + 34 * 60 + 30, TagoTimetableParser.parseHms("233430"));
        assertEquals(5 * 3600 + 3 * 60 + 30, TagoTimetableParser.parseHms("50330"));
        assertEquals(30 * 60, TagoTimetableParser.parseHms("003000"));
        assertEquals(-1, TagoTimetableParser.parseHms("0"));
        assertEquals(-1, TagoTimetableParser.parseHms(""));
        assertEquals(-1, TagoTimetableParser.parseHms(null));
        assertEquals(-1, TagoTimetableParser.parseHms("08:00:00"));
        assertEquals(-1, TagoTimetableParser.parseHms("086100"));
    }

    @Test
    @DisplayName("역 이름은 로더와 같은 정규화를 거친다 — 행선지 '서울역' 은 별칭으로 '서울', 끝의 '역' 은 뗀다")
    void normalizesNames() {
        var p = new TagoTimetableParser(new StationNameNormalizer(Map.of("서울역", "서울")));
        List<Segment> segs = List.of(new Segment(L, "서울", "신촌", 120, 1500, "avg"), new Segment(L, "신촌", "가좌", 120, 1500, "avg"));
        TagoTimetableParser.Result r = p.parse(List.of(row("가좌", "01", "D", "서울역", "070000"), row("신촌", "01", "U", "가좌역", "071000")), segs);

        assertEquals(Set.of(L + "|가좌|신촌", L + "|신촌|가좌"), r.slotWaits().keySet());
    }
}
