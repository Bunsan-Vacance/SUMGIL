package com.ssafy.s15p21a104.load.crowd;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 서울교통공사 지하철혼잡도정보(공공데이터포털 15071311) → congestion 행.
 * 열은 `구분 · 호선 · 역번호 · 역명 · 상하구분` + 30분 단위 시각 39개(5시30분~00시30분).
 * <p>
 * 스키마에 방향이 없어 상선·하선·내선·외선을 STATION 한 행으로 합치는데, 경로 추천에서 혼잡은 보수적으로 봐야 하므로
 * <b>방향별 최대값</b>을 쓴다(평균은 한 방향의 극심을 희석한다 — 원천 최대 144.6). LINE 은 그 노선 역들의 평균이다.
 * 원천이 덮지 않는 슬롯(01:00~05:29)과 1~8호선 밖 역은 <b>행을 만들지 않는다</b>.
 */
class CongestionParserTest {

    /** 시각 열 이름 → 값. 헤더 순서를 유지해야 하므로 LinkedHashMap 으로 만든다. */
    private static Map<String, String> row(String dow, String line, String no, String name, String direction,
                                           Map<String, String> times) {
        Map<String, String> r = new LinkedHashMap<>();
        r.put("구분", dow);
        r.put("호선", line);
        r.put("역번호", no);
        r.put("역명", name);
        r.put("상하구분", direction);
        r.putAll(times);
        return r;
    }

    private static Map<String, String> times(String... pairs) {
        Map<String, String> m = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) {
            m.put(pairs[i], pairs[i + 1]);
        }
        return m;
    }

    /** 역번호를 그대로 station_id 로 쓰는 시험용 표 (실제 매핑은 CrowdStationCodesTest 가 고정한다). */
    private static final CrowdStationCodes IDENTITY = new CrowdStationCodes() {
        @Override
        public Optional<String> stationIdOf(String crowdCode) {
            return crowdCode == null || crowdCode.isBlank() || crowdCode.startsWith("9")
                    ? Optional.empty() : Optional.of(crowdCode);
        }
    };

    private static CongestionRow find(List<CongestionRow> rows, String type, String id, int dow, int slot) {
        return rows.stream()
                .filter(r -> r.targetType().equals(type) && r.targetId().equals(id) && r.dowType() == dow && r.timeSlot() == slot)
                .findFirst().orElseThrow(() -> new AssertionError("행 없음: " + type + " " + id + " " + dow + "/" + slot));
    }

    @Test
    @DisplayName("시각 열을 30분 슬롯으로 바꾼다 — 5시30분=11, 08시30분=17, 23시30분=47, 00시00분=0, 00시30분=1")
    void mapsTimeColumnsToSlots() {
        var result = new CongestionParser(IDENTITY).parse(List.of(
                row("평일", "1호선", "150", "서울역", "상선",
                        times("5시30분", "8.8", "8시30분", "92.2", "23시30분", "6.5", "00시00분", "1.1", "00시30분", "0.5"))));

        assertEquals(List.of(0, 1, 11, 17, 47),
                result.rows().stream().filter(r -> r.targetType().equals("STATION")).map(CongestionRow::timeSlot).sorted().toList());
        assertEquals(new BigDecimal("92.2"), find(result.rows(), "STATION", "150", 0, 17).level());
        assertEquals(new BigDecimal("1.1"), find(result.rows(), "STATION", "150", 0, 0).level());
    }

    @Test
    @DisplayName("구분을 dow_type 으로 바꾼다 — 평일 0, 토요일 1, 일요일 2")
    void mapsDayTypes() {
        var result = new CongestionParser(IDENTITY).parse(List.of(
                row("평일", "1호선", "150", "서울역", "상선", times("8시30분", "92.2")),
                row("토요일", "1호선", "150", "서울역", "상선", times("8시30분", "40.1")),
                row("일요일", "1호선", "150", "서울역", "상선", times("8시30분", "30.0"))));

        assertEquals(new BigDecimal("92.2"), find(result.rows(), "STATION", "150", 0, 17).level());
        assertEquals(new BigDecimal("40.1"), find(result.rows(), "STATION", "150", 1, 17).level());
        assertEquals(new BigDecimal("30.0"), find(result.rows(), "STATION", "150", 2, 17).level());
    }

    @Test
    @DisplayName("방향 4종(상선·하선·내선·외선)을 STATION 한 행으로 합치고 최대값을 쓴다 — 상선 23.9 / 하선 92.2 → 92.2")
    void collapsesDirectionsByMax() {
        var result = new CongestionParser(IDENTITY).parse(List.of(
                row("평일", "1호선", "150", "서울역", "상선", times("8시30분", "23.9")),
                row("평일", "1호선", "150", "서울역", "하선", times("8시30분", "92.2")),
                row("평일", "2호선", "222", "강남", "내선", times("8시30분", "70.0")),
                row("평일", "2호선", "222", "강남", "외선", times("8시30분", "55.5"))));

        assertEquals(new BigDecimal("92.2"), find(result.rows(), "STATION", "150", 0, 17).level());
        assertEquals(new BigDecimal("70.0"), find(result.rows(), "STATION", "222", 0, 17).level());
        assertEquals(2, result.rows().stream().filter(r -> r.targetType().equals("STATION")).count());
    }

    @Test
    @DisplayName("환승역은 노선마다 그 노선 값으로 LINE 에 들어간다 — 서울역 1호선 92.2·4호선 50.0 이면 STATION 은 전체 최대 92.2, LINE 1001 은 1호선 값만(시청과 평균 66.1), LINE 1004 는 50.0")
    void transferStationContributesPerLine() {
        var result = new CongestionParser(IDENTITY).parse(List.of(
                row("평일", "1호선", "150", "서울역", "상선", times("8시30분", "92.2")),
                row("평일", "4호선", "150", "서울역", "상선", times("8시30분", "50.0")),
                row("평일", "1호선", "151", "시청", "상선", times("8시30분", "40.0"))));

        assertEquals(new BigDecimal("92.2"), find(result.rows(), "STATION", "150", 0, 17).level());
        assertEquals(new BigDecimal("66.1"), find(result.rows(), "LINE", "1001", 0, 17).level());
        assertEquals(new BigDecimal("50.0"), find(result.rows(), "LINE", "1004", 0, 17).level());
        assertEquals(2, result.rows().stream().filter(r -> r.targetType().equals("STATION")).count());
    }

    @Test
    @DisplayName("100 을 넘는 값도 그대로 저장한다 — 정원 대비 %라 넘을 수 있다 (원천 최대 144.6)")
    void keepsValuesOver100() {
        var result = new CongestionParser(IDENTITY).parse(List.of(
                row("평일", "2호선", "222", "강남", "상선", times("8시30분", "144.6"))));

        assertEquals(new BigDecimal("144.6"), find(result.rows(), "STATION", "222", 0, 17).level());
        assertEquals(1, result.stats().over100());
    }

    @Test
    @DisplayName("LINE 타깃은 그 노선 역들의 평균이다 — 1호선 서울역 92.2·시청 40.0 → 66.1 (소수 1자리)")
    void lineIsAverageOfStations() {
        var result = new CongestionParser(IDENTITY).parse(List.of(
                row("평일", "1호선", "150", "서울역", "상선", times("8시30분", "92.2")),
                row("평일", "1호선", "151", "시청", "상선", times("8시30분", "40.0"))));

        assertEquals(new BigDecimal("66.1"), find(result.rows(), "LINE", "1001", 0, 17).level());
    }

    @Test
    @DisplayName("역 ID 표에 없는 역번호는 행을 만들지 않고 한 줄로 집계 경고한다 — 값을 만들어 넣지 않는다")
    void unknownStationsAreSkippedWithOneWarning() {
        var parser = new CongestionParser(IDENTITY);
        var result = parser.parse(List.of(
                row("평일", "2호선", "9001", "성수E", "상선", times("8시30분", "50.0")),
                row("평일", "2호선", "9003", "신도림", "상선", times("8시30분", "60.0")),
                row("평일", "1호선", "150", "서울역", "상선", times("8시30분", "92.2"))));

        assertEquals(1, result.rows().stream().filter(r -> r.targetType().equals("STATION")).count());
        assertEquals(2, result.stats().unknownCodes());
        assertEquals(1, parser.warnings().size());
        assertTrue(parser.warnings().get(0).contains("성수E") && parser.warnings().get(0).contains("신도림"));
    }

    @Test
    @DisplayName("값이 비었거나 숫자가 아닌 칸은 건너뛴다 — 그 슬롯만 행이 없다")
    void skipsBlankCells() {
        var result = new CongestionParser(IDENTITY).parse(List.of(
                row("평일", "1호선", "150", "서울역", "상선", times("8시30분", "", "9시00분", "-", "9시30분", "62.5"))));

        assertEquals(List.of(19), result.rows().stream()
                .filter(r -> r.targetType().equals("STATION")).map(CongestionRow::timeSlot).toList());
    }

    @Test
    @DisplayName("line_id 가 없는 호선은 LINE 을 만들지 않지만 STATION 은 남긴다 — 원천에 새 노선이 들어와도 역 값은 쓴다")
    void unknownLineStillKeepsStation() {
        var parser = new CongestionParser(IDENTITY);
        var result = parser.parse(List.of(
                row("평일", "인천1호선", "3107", "검단호수공원", "상선", times("8시30분", "30.0"))));

        assertEquals(1, result.rows().stream().filter(r -> r.targetType().equals("STATION")).count());
        assertTrue(result.rows().stream().noneMatch(r -> r.targetType().equals("LINE")));
    }

    @Test
    @DisplayName("source 는 stat 이고 통계로 원천 행·역·슬롯 수를 돌려준다 (적재 로그용)")
    void reportsSourceAndStats() {
        var result = new CongestionParser(IDENTITY).parse(List.of(
                row("평일", "1호선", "150", "서울역", "상선", times("8시30분", "92.2", "9시00분", "58.0")),
                row("평일", "1호선", "151", "시청", "하선", times("8시30분", "40.0", "9시00분", "35.0"))));

        assertTrue(result.rows().stream().allMatch(r -> r.source().equals("stat")));
        assertEquals(2, result.stats().sourceRows());
        assertEquals(2, result.stats().stations());
        assertEquals(2, result.stats().slots());
    }

    @Test
    @DisplayName("모르는 구분·상하구분은 건너뛰고 경고한다 — 원천 표기가 바뀌면 조용히 사라지지 않게")
    void unknownDayOrDirectionIsWarned() {
        var parser = new CongestionParser(IDENTITY);
        List<Map<String, String>> rows = new ArrayList<>();
        rows.add(row("공휴일", "1호선", "150", "서울역", "상선", times("8시30분", "92.2")));
        var result = parser.parse(rows);

        assertTrue(result.rows().isEmpty());
        assertEquals(1, parser.warnings().size());
        assertTrue(parser.warnings().get(0).contains("공휴일"));
    }
}
