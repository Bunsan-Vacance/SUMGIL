package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 서울교통공사 "환승역거리 소요시간" 파일. 1~8호선 쪽에서만 기록되므로
 * 상대 노선(공항철도 등)이 1~8호선 밖이면 반대 방향을 만들어 준다.
 */
class TransferParserTest {

    private static Map<String, String> row(String line, String station, String toLine, String meters, String time) {
        return Map.of("연번", "0", "호선", line, "환승역명", station, "환승노선", toLine, "환승거리", meters, "환승소요시간", time);
    }

    private final TransferParser parser = new TransferParser(new StationNameNormalizer(Map.of("서울역", "서울")));

    @Test
    @DisplayName("행 하나를 (역, 출발노선, 도착노선, 도보초)로 바꾼다")
    void mapsRow() {
        List<TransferRecord> out = parser.parse(List.of(row("1", "서울역", "4호선", "159", "02:13")));

        // 4호선 쪽 행이 없으므로 반대 방향이 생성된다
        assertEquals(2, out.size());
        TransferRecord first = out.get(0);
        assertEquals("서울", first.stationName());
        assertEquals("1001", first.fromLineId());
        assertEquals("1004", first.toLineId());
        assertEquals(133, first.walkSec());
        assertEquals("1004", out.get(1).fromLineId());
        assertEquals("1001", out.get(1).toLineId());
    }

    @Test
    @DisplayName("양방향이 이미 파일에 있으면 중복 생성하지 않고 각 방향의 값을 그대로 쓴다")
    void keepsBothDirectionsWhenPresent() {
        List<TransferRecord> out = parser.parse(List.of(
                row("2", "왕십리", "5호선", "86", "01:12"),
                row("5", "왕십리", "2호선", "86", "01:12")));

        assertEquals(2, out.size());
    }

    @Test
    @DisplayName("1~8호선 밖 상대 노선(공항철도)은 반대 방향을 같은 값으로 만들어 준다")
    void addsReverseForExternalLines() {
        List<TransferRecord> out = parser.parse(List.of(row("1", "서울역", "공항철도", "309", "04:18")));

        assertEquals(2, out.size());
        assertEquals("1065", out.get(0).toLineId());
        assertEquals("1065", out.get(1).fromLineId());
        assertEquals(258, out.get(1).walkSec());
    }

    @Test
    @DisplayName("모르는 노선 표기는 건너뛰고 경고로 남긴다")
    void unknownLineIsSkippedWithWarning() {
        List<TransferRecord> out = parser.parse(List.of(row("5", "김포공항", "김포골드라인", "100", "01:20")));

        assertTrue(out.isEmpty());
        assertEquals(1, parser.warnings().size());
        assertTrue(parser.warnings().get(0).contains("김포골드라인"));
    }

    @Test
    @DisplayName("환승소요시간 mm:ss 를 초로 읽는다 — 02:13 → 133, 빈 값 → 0")
    void parsesMmSs() {
        assertEquals(133, TransferParser.parseMmSs("02:13"));
        assertEquals(0, TransferParser.parseMmSs("00:00"));
        assertEquals(110, TransferParser.parseMmSs("01:50"));
        assertEquals(0, TransferParser.parseMmSs(""));
    }
}
