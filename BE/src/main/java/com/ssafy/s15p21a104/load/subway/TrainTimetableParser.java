package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 서울교통공사 "서울 도시철도 열차운행시각표"(공공데이터포털 15098251) → 방향 있는 구간 + 슬롯별 기대 대기.
 * <p>
 * 행 1개 = 열차 1대의 역 1개 정차(호선·역사명·주중주말·급행여부·열차코드·도착·출발 시각). 열차(호선·요일·열차코드)별로
 * 정차를 시각순으로 정렬해 인접 역 쌍을 뽑는다. 구간 소요 = 다음 역 도착 − 이 역 출발, 여러 열차면 중앙값.
 * 급행(정차역을 건너뜀)은 인접 구간이 아니라 제외한다. 도착이 앞 역 출발보다 이른 행(00:00:00 자리표시)은 그 쌍만 버린다.
 * 42만 행을 한 번에 올리지 않도록 {@link #accept(Map)} 로 한 행씩 받고 압축 레코드만 보관한다.
 */
public final class TrainTimetableParser {

    /** 시각이 비어 있을 때 (첫 정차의 도착, 막 정차의 출발). */
    public static final int NONE = -1;
    private static final int EXAMPLE_LIMIT = 10;
    private static final Pattern HMS = Pattern.compile("^(\\d{1,2}):(\\d{2}):(\\d{2})$");

    /**
     * @param rows 받은 행 수, trains 완행 열차 수, expressTrains 제외한 급행 열차 수, anomalies 버린 구간 쌍 수,
     *             skippedRows 호선·요일·시각 표기 문제로 건너뛴 행 수, droppedEdges 표본이 모자라 버린 구간 수
     */
    public record Stats(int rows, int trains, int expressTrains, int anomalies, int skippedRows, int droppedEdges) {
    }

    /** @param slotWaits "lineId|출발역|도착역"(정규화 역명) → 요일×슬롯 기대 대기, lineIds 시각표가 덮는 노선 */
    public record Result(List<DirectedSegment> segments, Map<String, SlotWaits> slotWaits, Set<String> lineIds, Stats stats) {
    }

    private record Stop(String stationName, int arrivalSec, int departureSec) {
        int sortKey() {
            return departureSec != NONE ? departureSec : arrivalSec;
        }
    }

    private record TrainKey(String lineId, int dow, String trainCode) {
    }

    private static final class EdgeAcc {
        final List<Integer> travel = new ArrayList<>();
        final List<List<Integer>> departuresByDow = List.of(new ArrayList<>(), new ArrayList<>(), new ArrayList<>());
    }

    private final StationNameNormalizer normalizer;
    private final Map<TrainKey, List<Stop>> trains = new LinkedHashMap<>();
    private final Set<TrainKey> expressTrains = new HashSet<>();
    private final List<String> warnings = new ArrayList<>();
    private int rows;
    private int skippedRows;

    public TrainTimetableParser(StationNameNormalizer normalizer) {
        this.normalizer = normalizer;
    }

    /** 원천 행 하나를 받는다. 호선·요일·시각 표기를 모르면 건너뛰고 경고한다. */
    public void accept(Map<String, String> row) {
        rows++;
        String lineId = LineCodes.fromSeoulMetroLine(row.get("호선")).orElse(null);
        if (lineId == null) {
            skippedRows++;
            warnings.add("호선 표기를 모름: '" + row.get("호선") + "' (" + value(row, "역사명") + ")");
            return;
        }
        int dow = dowOf(value(row, "주중주말"));
        if (dow < 0) {
            skippedRows++;
            warnings.add("요일 표기를 모름: '" + value(row, "주중주말") + "' (" + value(row, "역사명") + ")");
            return;
        }
        TrainKey key = new TrainKey(lineId, dow, value(row, "열차코드"));
        if ("1".equals(value(row, "급행여부"))) {
            expressTrains.add(key);
            return;
        }
        int arrival;
        int departure;
        try {
            arrival = parseHms(value(row, "열차도착시간"));
            departure = parseHms(value(row, "열차출발시간"));
        } catch (IllegalArgumentException e) {
            skippedRows++;
            warnings.add("시각 표기를 모름: " + e.getMessage() + " (" + key.trainCode() + " " + value(row, "역사명") + ")");
            return;
        }
        String name = normalizer.normalize(value(row, "역사명"));
        trains.computeIfAbsent(key, k -> new ArrayList<>()).add(new Stop(name, arrival, departure));
    }

    /** 받은 행을 열차별로 정렬해 구간과 슬롯 대기를 만든다. */
    public Result finish() {
        Map<String, EdgeAcc> edges = new LinkedHashMap<>();
        Set<String> lineIds = new LinkedHashSet<>();
        int anomalies = 0;
        List<String> examples = new ArrayList<>();

        for (Map.Entry<TrainKey, List<Stop>> entry : trains.entrySet()) {
            TrainKey key = entry.getKey();
            lineIds.add(key.lineId());
            List<Stop> stops = entry.getValue().stream()
                    .filter(s -> s.sortKey() != NONE)
                    .sorted(Comparator.comparingInt(Stop::sortKey))
                    .toList();
            for (int i = 1; i < stops.size(); i++) {
                Stop a = stops.get(i - 1);
                Stop b = stops.get(i);
                if (a.departureSec() == NONE || b.arrivalSec() == NONE) {
                    continue;
                }
                int travel = b.arrivalSec() - a.departureSec();
                if (travel <= 0 || a.stationName().equals(b.stationName())) {
                    anomalies++;
                    if (examples.size() < EXAMPLE_LIMIT) {
                        examples.add(key.trainCode() + " " + a.stationName() + "(" + hms(a.departureSec()) + ")→"
                                + b.stationName() + "(" + hms(b.arrivalSec()) + ")");
                    }
                    continue;
                }
                EdgeAcc acc = edges.computeIfAbsent(key.lineId() + "|" + a.stationName() + "|" + b.stationName(), k -> new EdgeAcc());
                acc.travel.add(travel);
                acc.departuresByDow.get(key.dow()).add(a.departureSec());
            }
        }
        if (anomalies > 0) {
            warnings.add("소요시간 이상치 " + anomalies + "건 (도착 ≤ 출발 또는 같은 역 연속, 표본에서 제외): "
                    + String.join(", ", examples) + (anomalies > EXAMPLE_LIMIT ? ", …" : ""));
        }

        List<DirectedSegment> segments = new ArrayList<>(edges.size());
        Map<String, SlotWaits> slotWaits = new LinkedHashMap<>();
        for (Map.Entry<String, EdgeAcc> e : edges.entrySet()) {
            String[] k = e.getKey().split("\\|", 3);
            segments.add(new DirectedSegment(k[0], k[1], k[2], median(e.getValue().travel), "timetable"));
            slotWaits.put(e.getKey(), SlotWaits.fromDepartures(e.getValue().departuresByDow));
        }
        return new Result(segments, slotWaits, lineIds,
                new Stats(rows, trains.size(), expressTrains.size(), anomalies, skippedRows, 0));
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    /** "05:20:30" → 19,230. 자정 넘는 "24:30:00" → 88,200 (운행일 기준). 빈 값은 {@link #NONE}. */
    public static int parseHms(String text) {
        if (text == null || text.isBlank()) {
            return NONE;
        }
        Matcher m = HMS.matcher(text.trim());
        if (!m.matches()) {
            throw new IllegalArgumentException("'" + text + "'");
        }
        return Integer.parseInt(m.group(1)) * 3600 + Integer.parseInt(m.group(2)) * 60 + Integer.parseInt(m.group(3));
    }

    private static String hms(int sec) {
        return sec == NONE ? "-" : String.format("%02d:%02d:%02d", sec / 3600, (sec % 3600) / 60, sec % 60);
    }

    /** 주중주말: DAY 평일 0 · SAT 토 1 · END 일·공휴일 2. */
    static int dowOf(String dayType) {
        return switch (dayType) {
            case "DAY" -> 0;
            case "SAT" -> 1;
            case "END" -> 2;
            default -> -1;
        };
    }

    private static int median(List<Integer> values) {
        List<Integer> sorted = values.stream().sorted().toList();
        int n = sorted.size();
        if (n % 2 == 1) {
            return sorted.get(n / 2);
        }
        return (int) Math.round((sorted.get(n / 2 - 1) + sorted.get(n / 2)) / 2.0);
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }
}
