package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 서울교통공사 "역간거리 및 소요시간" 파일은 호선별로 역을 운행 순서대로 나열한다.
 * 소요시간 00:00 은 노선(또는 지선) 시작점이고, 지선 첫 역은 직전 행이 아니라 분기역에 붙는다.
 */
class SeoulMetroTimetableParserTest {

    private static Map<String, String> row(String line, String station, String time, String km) {
        return Map.of("연번", "0", "호선", line, "역명", station, "소요시간", time, "역간거리(km)", km, "호선별누계(km)", "0");
    }

    private final StationNameNormalizer normalizer = new StationNameNormalizer(Map.of("서울역", "서울"));

    @Test
    @DisplayName("연속 행을 구간으로 잇고 mm:ss 를 초로 바꾼다")
    void consecutiveRowsBecomeSegments() {
        var parser = new SeoulMetroTimetableParser(normalizer, Map.of());
        List<Segment> segments = parser.parse(List.of(
                row("1", "서울역", "00:00", "0"),
                row("1", "시청", "02:00", "1.1"),
                row("1", "종각", "01:30", "1.0")));

        assertEquals(2, segments.size());
        Segment first = segments.get(0);
        assertEquals("1001", first.lineId());
        assertEquals("서울", first.fromName());
        assertEquals("시청", first.toName());
        assertEquals(120, first.travelSec());
        assertEquals(1100, first.distanceM());
        assertEquals("timetable", first.source());
        assertEquals(90, segments.get(1).travelSec());
    }

    @Test
    @DisplayName("순환선(2호선)은 마지막 행이 첫 역으로 돌아와도 하나의 구간으로 잇는다")
    void loopClosesBackToStart() {
        var parser = new SeoulMetroTimetableParser(normalizer, Map.of());
        List<Segment> segments = parser.parse(List.of(
                row("2", "시청", "00:00", "0"),
                row("2", "을지로입구", "01:30", "0.7"),
                row("2", "충정로", "01:00", "0.9"),
                row("2", "시청", "01:30", "1.1")));

        assertEquals(3, segments.size());
        assertEquals("충정로", segments.get(2).fromName());
        assertEquals("시청", segments.get(2).toName());
    }

    @Test
    @DisplayName("지선 첫 역은 분기역(anchor)에 붙는다 — 2호선 용답은 시청이 아니라 성수에서 출발")
    void branchAttachesToAnchor() {
        Map<String, Map<String, String>> anchors = Map.of("1002", Map.of("용답", "성수", "도림천", "신도림"));
        var parser = new SeoulMetroTimetableParser(normalizer, anchors);
        List<Segment> segments = parser.parse(List.of(
                row("2", "시청", "00:00", "0"),
                row("2", "성수", "01:00", "1.0"),
                row("2", "시청", "01:30", "1.1"),
                row("2", "용답", "03:00", "2.3"),
                row("2", "신답", "01:30", "1.2"),
                row("2", "도림천", "01:30", "1.0"),
                row("2", "양천구청", "02:30", "1.4")));

        List<String> pairs = segments.stream().map(s -> s.fromName() + ">" + s.toName()).toList();
        assertEquals(List.of("시청>성수", "성수>시청", "성수>용답", "용답>신답", "신도림>도림천", "도림천>양천구청"), pairs);
        assertEquals(180, segments.get(2).travelSec());
    }

    @Test
    @DisplayName("호선이 바뀌면 이전 호선의 마지막 역과 잇지 않는다")
    void lineChangeResetsPrevious() {
        var parser = new SeoulMetroTimetableParser(normalizer, Map.of());
        List<Segment> segments = parser.parse(List.of(
                row("1", "서울역", "00:00", "0"),
                row("1", "시청", "02:00", "1.1"),
                row("3", "지축", "00:00", "0"),
                row("3", "구파발", "02:00", "1.6")));

        assertEquals(2, segments.size());
        assertTrue(segments.stream().noneMatch(s -> s.fromName().equals("시청") && s.toName().equals("지축")));
        assertEquals("1003", segments.get(1).lineId());
    }

    @Test
    @DisplayName("소요시간 표기 mm:ss 파싱")
    void parsesMmSs() {
        assertEquals(133, SeoulMetroTimetableParser.parseMmSs("02:13"));
        assertEquals(0, SeoulMetroTimetableParser.parseMmSs("00:00"));
        assertEquals(110, SeoulMetroTimetableParser.parseMmSs("01:50"));
    }
}
