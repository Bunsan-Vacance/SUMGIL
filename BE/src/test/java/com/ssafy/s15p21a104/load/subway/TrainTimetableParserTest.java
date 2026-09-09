package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

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
    @DisplayName("열차의 정차 행이 뒤섞여 있어도 시각순으로 정렬해 인접 역 쌍을 만든다 — 소요 = 다음 역 도착 − 이 역 출발")
    void sortsStopsByTimeAndBuildsSegments() {
        TrainTimetableParser.Result r = parse(parser, List.of(
                stop("2", "까치산", "DAY", "UP", "0", "5902", "05:26:00", ""),
                stop("2", "도림천", "DAY", "UP", "0", "5902", "", "05:17:00"),
                stop("2", "신정네거리", "DAY", "UP", "0", "5902", "05:23:00", "05:23:30"),
                stop("2", "양천구청", "DAY", "UP", "0", "5902", "05:19:30", "05:20:00")));

        assertEquals(3, r.segments().size());
        assertEquals(150, seg(r.segments(), "도림천", "양천구청").travelSec());
        assertEquals(180, seg(r.segments(), "양천구청", "신정네거리").travelSec());
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
