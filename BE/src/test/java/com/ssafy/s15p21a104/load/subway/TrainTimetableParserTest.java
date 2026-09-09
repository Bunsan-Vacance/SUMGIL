package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 서울교통공사 열차운행시각표(공공데이터포털 15098251) → 방향 있는 구간 + 슬롯별 대기.
 * 행 1개 = 열차 1대의 역 1개 정차. 열차별로 시각순 정렬해 인접 역 쌍을 뽑는다. 완행만 쓴다.
 */
class TrainTimetableParserTest {

    private static Map<String, String> stop(String line, String name, String day, String dir, String express,
                                            String train, String arr, String dep) {
        Map<String, String> m = new HashMap<>();
        m.put("고유번호", "1");
        m.put("호선", line);
        m.put("역사코드", "0000");
        m.put("역사명", name);
        m.put("주중주말", day);
        m.put("방향", dir);
        m.put("급행여부", express);
        m.put("열차코드", train);
        m.put("열차도착시간", arr);
        m.put("열차출발시간", dep);
        m.put("출발역", "기점");
        m.put("도착역", "종점");
        return m;
    }

    private static TrainTimetableParser.Result parse(TrainTimetableParser parser, List<Map<String, String>> rows) {
        rows.forEach(parser::accept);
        return parser.finish();
    }

    private static DirectedSegment seg(List<DirectedSegment> segs, String from, String to) {
        return segs.stream().filter(s -> s.fromName().equals(from) && s.toName().equals(to)).findFirst().orElseThrow();
    }

    private final TrainTimetableParser parser = new TrainTimetableParser(new StationNameNormalizer(Map.of()));

    @Test
    @DisplayName("열차의 정차 행이 뒤섞여 있어도 시각순으로 정렬해 인접 역 쌍을 만든다 — 소요 = 다음 역 출발 − 이 역 출발 (도착역 정차시간 포함)")
    void sortsStopsByTimeAndBuildsSegments() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("2", "까치산", "DAY", "UP", "0", "5902", "05:26:00", ""),
                stop("2", "도림천", "DAY", "UP", "0", "5902", "", "05:17:00"),
                stop("2", "신정네거리", "DAY", "UP", "0", "5902", "05:23:00", "05:23:30"),
                stop("2", "양천구청", "DAY", "UP", "0", "5902", "05:19:30", "05:20:00")));

        assertEquals(3, r.segments().size());
        assertEquals(180, seg(r.segments(), "도림천", "양천구청").travelSec());
        assertEquals(210, seg(r.segments(), "양천구청", "신정네거리").travelSec());
        assertEquals(150, seg(r.segments(), "신정네거리", "까치산").travelSec());
        assertEquals("1002", seg(r.segments(), "도림천", "양천구청").lineId());
        assertEquals("timetable", seg(r.segments(), "도림천", "양천구청").source());
        assertEquals(Set.of("1002"), r.lineIds());
    }

    @Test
    @DisplayName("반대 방향 열차가 있어야 역방향 구간이 생긴다 — 임의로 역방향을 만들지 않는다 (6호선 응암순환)")
    void directionComesOnlyFromTrains() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("6", "응암", "DAY", "UP", "0", "6001", "", "05:00:00"),
                stop("6", "역촌", "DAY", "UP", "0", "6001", "05:02:00", "05:02:30"),
                stop("6", "불광", "DAY", "UP", "0", "6001", "05:04:00", "")));

        assertEquals(2, r.segments().size());
        assertTrue(r.segments().stream().noneMatch(s -> s.fromName().equals("역촌") && s.toName().equals("응암")));
    }

    @Test
    @DisplayName("같은 구간을 여러 열차가 지나면 소요시간은 중앙값이다 — 90·120·120 → 120")
    void travelIsMedianAcrossTrains() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("2", "강남", "DAY", "IN", "0", "A", "", "08:00:00"), stop("2", "역삼", "DAY", "IN", "0", "A", "08:01:30", ""),
                stop("2", "강남", "DAY", "IN", "0", "B", "", "08:10:00"), stop("2", "역삼", "DAY", "IN", "0", "B", "08:12:00", ""),
                stop("2", "강남", "DAY", "IN", "0", "C", "", "08:20:00"), stop("2", "역삼", "DAY", "IN", "0", "C", "08:22:00", "")));

        assertEquals(120, seg(r.segments(), "강남", "역삼").travelSec());
    }

    @Test
    @DisplayName("급행 열차(급행여부=1)는 구간을 만들지 않고 건수만 센다 — 정차역을 건너뛰어 인접 구간이 아니다")
    void expressTrainsAreExcluded() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("9", "김포공항", "DAY", "UP", "1", "E1", "", "06:00:00"),
                stop("9", "마곡나루", "DAY", "UP", "1", "E1", "06:05:00", ""),
                stop("9", "김포공항", "DAY", "UP", "0", "L1", "", "06:03:00"),
                stop("9", "공항시장", "DAY", "UP", "0", "L1", "06:05:00", "")));

        assertEquals(1, r.segments().size());
        assertEquals("공항시장", r.segments().get(0).toName());
        assertEquals(1, r.stats().expressTrains());
    }

    @Test
    @DisplayName("도착이 앞 역 출발보다 이른 행(00:00:00 자리표시)은 그 쌍만 버리고 한 줄 집계 경고를 남긴다")
    void anomalousArrivalIsSkippedWithWarning() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("1", "광운대", "DAY", "UP", "0", "K1602", "", "06:40:00"),
                stop("1", "월계", "DAY", "UP", "0", "K1602", "00:00:00", "06:41:30"),
                stop("1", "녹천", "DAY", "UP", "0", "K1602", "06:43:00", "")));

        assertEquals(1, r.segments().size());
        assertEquals("월계", r.segments().get(0).fromName());
        assertEquals(1, r.stats().anomalies());
        assertTrue(parser.warnings().stream().anyMatch(w -> w.contains("이상치") && w.contains("K1602")));
    }

    @Test
    @DisplayName("종착역은 출발 시각이 없으니 도착 시각으로 잰다 — 그 구간만 정차시간이 붙지 않는다")
    void terminalStopIsMeasuredToArrival() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("3", "고속터미널", "DAY", "UP", "0", "3305", "", "21:06:00"),
                stop("3", "교대", "DAY", "UP", "0", "3305", "21:08:00", "21:08:30"),
                stop("3", "남부터미널", "DAY", "UP", "0", "3305", "21:10:30", "")));

        assertEquals(150, seg(r.segments(), "고속터미널", "교대").travelSec());
        assertEquals(120, seg(r.segments(), "교대", "남부터미널").travelSec());
    }

    @Test
    @DisplayName("출발 시각이 도착보다 이른 자리표시(00:00:00) 행은 출발이 없는 것으로 보고 도착 시각으로 정렬한다 — 중간 역을 건너뛴 유령 구간을 만들지 않는다")
    void placeholderDepartureDoesNotReorderStops() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("4", "오이도", "DAY", "UP", "0", "4422K", "", "06:42:00"),
                stop("4", "정왕", "DAY", "UP", "0", "4422K", "06:44:30", "06:45:00"),
                stop("4", "신길온천", "DAY", "UP", "0", "4422K", "06:47:00", "00:00:00"),
                stop("4", "안산", "DAY", "UP", "0", "4422K", "06:49:00", "06:49:30")));

        assertTrue(r.segments().stream().noneMatch(s -> s.fromName().equals("정왕") && s.toName().equals("안산")),
                "신길온천을 건너뛴 정왕→안산 구간이 생기면 안 된다");
        assertEquals(180, seg(r.segments(), "오이도", "정왕").travelSec());
        assertEquals(120, seg(r.segments(), "정왕", "신길온천").travelSec());
        assertEquals(2, r.segments().size());
        assertTrue(parser.warnings().stream().anyMatch(w -> w.contains("출발 시각") && w.contains("신길온천")));
    }

    @Test
    @DisplayName("표본이 그 노선 중앙값의 10% 도 안 되는 구간은 회송 열차가 중간 역 없이 남긴 유령 구간으로 보고 버리고 경고한다")
    void lowSupportEdgesAreDropped() {
        List<Map<String, String>> rows = new ArrayList<>();
        for (int i = 0; i < 12; i++) {
            String code = "L" + i;
            String hour = String.format("%02d", 6 + i);
            rows.add(stop("5", "방화", "DAY", "UP", "0", code, "", hour + ":00:00"));
            rows.add(stop("5", "개화산", "DAY", "UP", "0", code, hour + ":02:00", hour + ":02:30"));
            rows.add(stop("5", "김포공항", "DAY", "UP", "0", code, hour + ":05:00", ""));
        }
        rows.add(stop("5", "방화", "DAY", "UP", "0", "5901", "", "05:24:30"));
        rows.add(stop("5", "김포공항", "DAY", "UP", "0", "5901", "05:35:30", ""));

        TrainTimetableParser.Result r = parse(parser, rows);

        assertEquals(2, r.segments().size());
        assertEquals(150, seg(r.segments(), "방화", "개화산").travelSec());
        assertEquals(150, seg(r.segments(), "개화산", "김포공항").travelSec());
        assertTrue(r.segments().stream().noneMatch(s -> s.fromName().equals("방화") && s.toName().equals("김포공항")));
        assertFalse(r.slotWaits().containsKey("1005|방화|김포공항"));
        assertEquals(1, r.stats().droppedEdges());
        assertTrue(parser.warnings().stream().anyMatch(w -> w.contains("표본") && w.contains("김포공항")));
    }

    @Test
    @DisplayName("역명은 정규화기를 거친다 — 서울역 → 서울")
    void normalizesStationNames() {
        var aliased = new TrainTimetableParser(new StationNameNormalizer(Map.of("서울역", "서울")));
        TrainTimetableParser.Result r = parse(aliased, List.of(
                stop("1", "서울역", "DAY", "UP", "0", "T", "", "05:20:30"),
                stop("1", "시청", "DAY", "UP", "0", "T", "05:22:00", "")));

        assertEquals("서울", r.segments().get(0).fromName());
    }

    @Test
    @DisplayName("주중주말 DAY·SAT·END 는 dow_type 0·1·2 이고, 슬롯별 대기는 그 요일에만 채워진다 (없는 요일은 86,400)")
    void dayTypesMapToDowAndWaits() {
        // 토요일 08:00 슬롯을 10분 간격 4대로 채운다 → 기대 대기 300초
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("2", "강남", "SAT", "IN", "0", "A", "", "08:00:00"), stop("2", "역삼", "SAT", "IN", "0", "A", "08:02:00", ""),
                stop("2", "강남", "SAT", "IN", "0", "B", "", "08:10:00"), stop("2", "역삼", "SAT", "IN", "0", "B", "08:12:00", ""),
                stop("2", "강남", "SAT", "IN", "0", "C", "", "08:20:00"), stop("2", "역삼", "SAT", "IN", "0", "C", "08:22:00", ""),
                stop("2", "강남", "SAT", "IN", "0", "D", "", "08:30:00"), stop("2", "역삼", "SAT", "IN", "0", "D", "08:32:00", "")));

        SlotWaits w = r.slotWaits().get("1002|강남|역삼");
        assertEquals(300, w.wait(1, 16));
        assertEquals(SlotWaits.NO_SERVICE, w.wait(0, 16));
        assertEquals(SlotWaits.NO_SERVICE, w.wait(2, 16));
    }

    @Test
    @DisplayName("자정 넘는 시각 표기를 운행일 기준 초로 읽는다 — 24:30:00 → 88,200")
    void parsesAfterMidnightTimes() {
        assertEquals(88200, TrainTimetableParser.parseHms("24:30:00"));
        assertEquals(19230, TrainTimetableParser.parseHms("05:20:30"));
        assertEquals(TrainTimetableParser.NONE, TrainTimetableParser.parseHms(""));
    }

    @Test
    @DisplayName("호선 표기를 모르거나 요일 표기를 모르는 행은 건너뛰고 경고한다")
    void unknownLineOrDayIsSkipped() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("X", "가", "DAY", "UP", "0", "T", "", "05:00:00"),
                stop("1", "나", "HOL", "UP", "0", "T", "", "05:00:00")));

        assertTrue(r.segments().isEmpty());
        assertEquals(2, r.stats().skippedRows());
        assertEquals(2, parser.warnings().size());
    }

    @Test
    @DisplayName("통계: 행 수·열차 수·급행 수·이상치 수를 보고한다")
    void reportsStats() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("2", "강남", "DAY", "IN", "0", "A", "", "08:00:00"), stop("2", "역삼", "DAY", "IN", "0", "A", "08:02:00", ""),
                stop("2", "강남", "DAY", "IN", "1", "E", "", "08:05:00"), stop("2", "선릉", "DAY", "IN", "1", "E", "08:08:00", "")));

        assertEquals(4, r.stats().rows());
        assertEquals(1, r.stats().trains());
        assertEquals(1, r.stats().expressTrains());
        assertEquals(0, r.stats().anomalies());
    }
}
