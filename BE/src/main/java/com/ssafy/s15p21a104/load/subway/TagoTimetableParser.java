package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * TAGO 지하철정보(공공데이터포털 15098554)의 역별 시각표 → 열차운행시각표가 덮지 않는 노선(KTDB 거리 구간)의 슬롯별 기대 대기 (S15P21A104-243).
 *
 * <p>입력은 {@code BE/scripts/data/tago-timetable-fetch.mjs} 가 만든 CSV 다 — 행 하나 = 역 하나에서 어느 행선지(종착역)로 떠나는
 * 열차 하나의 출발 시각. 열차 번호가 없어 구간 소요는 만들지 못하고 {@code wait_sec} 만 만든다(소요는 KTDB 거리 ÷ 표정속도 그대로).
 *
 * <p><b>방향 배정.</b> 우리 엣지는 방향이 있다(from→to). 어느 열차가 어느 이웃 쪽으로 가는지는 행선지로 판단한다 —
 * 행선지가 from 의 이웃 N 너머에 있으면(N 에서 출발해 from 을 지나지 않고 행선지에 닿으면) from→N 의 출발이다.
 * 노선이 분기해도(경의중앙 서울역 지선, 경춘 광운대 지선) 이 규칙으로 갈린다. 행선지를 노선 역 목록에서 못 찾거나 비어 있으면
 * 세 단계로 대체한다({@link #resolveByFallback}): 같은 역·같은 U/D 의 다수결 이웃 → 노선 전체에서 그 U/D 가 향한 종점의 다수결 →
 * 반대 U/D 가 풀린 이웃의 나머지. 전부 실패하면 버리고 센다 — 추측으로 채우지 않는다. 2026-09-18 실측: 서해선은 역마다 한쪽 U/D 의
 * 행선지가 비어 와서(2,968행) 두 번째 규칙이 필요했다.
 *
 * <p>시각은 {@code HHmmss} 문자열이다. 자정을 넘는 열차는 {@code 00xxxx} 로 오는데 {@link SlotWaits} 가 24시간으로 접어 슬롯을 정하므로
 * 운행일 보정 없이 그대로 넣는다. {@code "0"}·빈 값은 출발 시각이 없는 행(종착 도착 등)이라 건너뛴다.
 */
public final class TagoTimetableParser {

    /**
     * @param slotWaits "lineId|출발역|도착역"(정규화 역명) → 요일×슬롯 기대 대기. {@link SubwayGraphBuilder} 가 station_id 키로 바꾼다
     * @param stats     행 처리 집계
     */
    public record Result(Map<String, SlotWaits> slotWaits, Stats stats) {
    }

    /**
     * @param rows               읽은 행
     * @param used               대기 계산에 들어간 행
     * @param noDeparture        출발 시각이 없는 행("0"·빈 값) — 종착 도착 등
     * @param terminalHere       행선지가 그 역 자신인 행 — 이 역이 종착인 열차, 출발이 아니다
     * @param unresolvedTerminal 행선지를 노선 역 목록에서 못 찾은 행 (이 중 fallbackUpDown 만큼은 U/D 다수결로 살렸다)
     * @param fallbackUpDown     U/D 다수결로 방향을 정한 행
     * @param dropped            방향을 못 정해 버린 행 (미해결 행선지에 다수결도 없음, 모르는 노선·역·요일, 이웃 둘 이상에 닿는 행선지)
     * @param lineIds            대기를 붙인 노선
     * @param edgesCovered       대기가 붙은 방향 엣지 수
     * @param edgesTotal         대상 노선의 방향 엣지 수 (무방향 구간 × 2)
     * @param saturdayFromHoliday 토요일(02) 행이 하나도 없어 휴일(03) 시각표를 토요일에도 쓴 노선 — 2026-09-18 실측: 우이신설 외 8개 노선 전부
     */
    public record Stats(int rows, int used, int noDeparture, int terminalHere, int unresolvedTerminal, int fallbackUpDown,
                        int dropped, Set<String> lineIds, int edgesCovered, int edgesTotal, Set<String> saturdayFromHoliday) {
    }

    private static final int EXAMPLE_LIMIT = 5;

    private final StationNameNormalizer normalizer;
    private final List<String> warnings = new ArrayList<>();

    public TagoTimetableParser(StationNameNormalizer normalizer) {
        this.normalizer = normalizer;
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    /** 한 행의 판정에 필요한 값. */
    private record Row(String lineId, String station, String upDown, int dow, int departureSec, String terminal) {
    }

    /**
     * @param rows     CSV 행 — line_id, station_name, daily_type, up_down, end_station_nm, dep_time
     * @param segments 대상 노선의 무방향 구간(KTDB). 노선별 이웃 관계와 역 목록을 여기서 얻는다
     */
    public Result parse(List<Map<String, String>> rows, List<Segment> segments) {
        warnings.clear();
        Map<String, Map<String, Set<String>>> adjacency = adjacency(segments);

        int noDeparture = 0;
        int terminalHere = 0;
        int dropped = 0;
        Map<String, Integer> droppedReasons = new LinkedHashMap<>();
        List<Row> resolvedNow = new ArrayList<>();      // 행선지로 방향이 정해진 행 (terminal 자리에 이웃 이름)
        List<Row> pending = new ArrayList<>();          // 행선지 미해결 — U/D 다수결 대기
        // (line|station|U/D) → 이웃 → 건수. 미해결 행의 방향을 정하는 다수결 표
        Map<String, Map<String, Integer>> orientation = new HashMap<>();
        // (line|U/D) → 행선지 → 건수. 노선 전체에서 U/D 가 어느 종점 쪽인지 — 그 역에 풀린 행이 없을 때의 두 번째 대체
        Map<String, Map<String, Integer>> lineTerminals = new HashMap<>();

        for (Map<String, String> raw : rows) {
            String lineId = value(raw, "line_id");
            String station = normalizer.normalizeStation(value(raw, "station_name"));
            int dep = parseHms(value(raw, "dep_time"));
            if (dep < 0) {
                noDeparture++;
                continue;
            }
            int dow = dowOf(value(raw, "daily_type"));
            Map<String, Set<String>> lineAdj = adjacency.get(lineId);
            if (dow < 0 || lineAdj == null || !lineAdj.containsKey(station)) {
                dropped++;
                count(droppedReasons, dow < 0 ? "요일 코드 모름 '" + value(raw, "daily_type") + "'"
                        : lineAdj == null ? "구간 없는 노선 " + lineId : "노선 " + lineId + " 구간에 없는 역 '" + station + "'");
                continue;
            }
            String terminal = normalizer.normalizeStation(value(raw, "end_station_nm"));
            if (terminal.equals(station)) {
                terminalHere++;
                continue;
            }
            Row row = new Row(lineId, station, value(raw, "up_down"), dow, dep, terminal);
            Set<String> neighbors = lineAdj.get(station);
            List<String> toward = new ArrayList<>();
            for (String n : neighbors) {
                if (reachableWithout(lineAdj, n, station).contains(terminal)) {
                    toward.add(n);
                }
            }
            if (toward.size() == 1) {
                resolvedNow.add(new Row(lineId, station, row.upDown(), dow, dep, toward.get(0)));
                count(orientation.computeIfAbsent(orientationKey(row), k -> new HashMap<>()), toward.get(0));
                count(lineTerminals.computeIfAbsent(lineId + "|" + row.upDown(), k -> new HashMap<>()), terminal);
            } else if (toward.isEmpty()) {
                pending.add(row);
            } else {
                dropped++;
                count(droppedReasons, "행선지 '" + terminal + "' 이(가) " + station + " 의 이웃 둘 이상 너머에 있음 (" + lineId + ")");
            }
        }

        int fallback = 0;
        int unresolved = pending.size();
        Map<String, Integer> unresolvedExamples = new LinkedHashMap<>();
        for (Row row : pending) {
            String neighbor = resolveByFallback(row, adjacency.get(row.lineId()), orientation, lineTerminals);
            if (neighbor == null) {
                dropped++;
                count(unresolvedExamples, row.lineId() + " " + row.station() + " → '" + row.terminal() + "' (" + row.upDown() + ")");
                continue;
            }
            fallback++;
            resolvedNow.add(new Row(row.lineId(), row.station(), row.upDown(), row.dow(), row.departureSec(), neighbor));
        }

        Map<String, List<List<Integer>>> departures = new LinkedHashMap<>();
        Set<String> lineIds = new LinkedHashSet<>();
        Set<String> linesWithSaturday = new HashSet<>();
        Set<String> linesWithHoliday = new HashSet<>();
        for (Row row : resolvedNow) {
            String key = row.lineId() + "|" + row.station() + "|" + row.terminal();
            departures.computeIfAbsent(key, k -> List.of(new ArrayList<>(), new ArrayList<>(), new ArrayList<>()))
                    .get(row.dow()).add(row.departureSec());
            lineIds.add(row.lineId());
            if (row.dow() == 1) {
                linesWithSaturday.add(row.lineId());
            } else if (row.dow() == 2) {
                linesWithHoliday.add(row.lineId());
            }
        }
        // 토요일 시각표가 아예 없는 노선은 휴일 시각표를 토요일에도 쓴다 — TAGO 가 코레일·사철 노선의 토·일을 03 하나로 준다(2026-09-18 실측,
        // 우이신설만 02·03 을 따로 준다). "값을 만들어 넣지 않는다" 의 예외가 아니다: 원천이 토·일을 한 요일 유형으로 묶어 준 것이다.
        Set<String> saturdayFromHoliday = new LinkedHashSet<>();
        for (String lineId : lineIds) {
            if (!linesWithSaturday.contains(lineId) && linesWithHoliday.contains(lineId)) {
                saturdayFromHoliday.add(lineId);
            }
        }
        Map<String, SlotWaits> slotWaits = new LinkedHashMap<>();
        departures.forEach((key, byDow) -> {
            List<List<Integer>> table = byDow;
            if (saturdayFromHoliday.contains(key.substring(0, key.indexOf('|')))) {
                table = List.of(byDow.get(0), byDow.get(2), byDow.get(2));
            }
            slotWaits.put(key, SlotWaits.fromDepartures(table));
        });
        if (!saturdayFromHoliday.isEmpty()) {
            warnings.add("토요일(02) 시각표가 없어 휴일(03) 시각표를 토요일에도 쓴 노선: " + saturdayFromHoliday);
        }

        int edgesTotal = 0;
        for (Segment s : segments) {
            if (lineIds.contains(s.lineId())) {
                edgesTotal += 2;
            }
        }
        droppedReasons.forEach((reason, n) -> warnings.add(reason + ": " + n + "행 버림"));
        if (!unresolvedExamples.isEmpty()) {
            List<String> examples = new ArrayList<>();
            unresolvedExamples.entrySet().stream().limit(EXAMPLE_LIMIT)
                    .forEach(e -> examples.add(e.getKey() + " ×" + e.getValue()));
            warnings.add("행선지를 노선 역 목록에서 못 찾고 U/D 다수결도 없어 버린 (역·행선지) " + unresolvedExamples.size()
                    + "종 — 예: " + String.join(", ", examples) + ". 이름 차이면 conf/station-aliases.csv 에 별칭을 더한다");
        }
        return new Result(slotWaits, new Stats(rows.size(), resolvedNow.size(), noDeparture, terminalHere, unresolved, fallback,
                dropped, lineIds, slotWaits.size(), edgesTotal, saturdayFromHoliday));
    }

    /**
     * 행선지로 방향을 못 정한 행의 대체 규칙 — 순서대로 시도하고 전부 실패하면 null.
     * <ol>
     *   <li>같은 역·같은 U/D 에서 행선지로 풀린 행들의 다수결 이웃</li>
     *   <li>노선 전체에서 그 U/D 가 향한 행선지의 다수결 → 그 행선지가 어느 이웃 너머인지 (서해선처럼 역마다 한쪽 U/D 의 행선지가 비어 오는 경우)</li>
     *   <li>이웃이 둘인 역에서 반대 U/D 가 한 이웃으로 풀렸으면 나머지 이웃 (상·하행 코드는 한 역에서 서로 반대다)</li>
     * </ol>
     */
    private static String resolveByFallback(Row row, Map<String, Set<String>> lineAdj,
                                            Map<String, Map<String, Integer>> orientation,
                                            Map<String, Map<String, Integer>> lineTerminals) {
        String neighbor = majority(orientation.get(orientationKey(row)));
        if (neighbor != null) {
            return neighbor;
        }
        Set<String> neighbors = lineAdj.get(row.station());
        String lineTerminal = majority(lineTerminals.get(row.lineId() + "|" + row.upDown()));
        if (lineTerminal != null) {
            List<String> toward = new ArrayList<>();
            for (String n : neighbors) {
                if (reachableWithout(lineAdj, n, row.station()).contains(lineTerminal)) {
                    toward.add(n);
                }
            }
            if (toward.size() == 1) {
                return toward.get(0);
            }
        }
        if (neighbors.size() == 2) {
            String opposite = "U".equals(row.upDown()) ? "D" : "U";
            String other = majority(orientation.get(row.lineId() + "|" + row.station() + "|" + opposite));
            if (other != null) {
                for (String n : neighbors) {
                    if (!n.equals(other)) {
                        return n;
                    }
                }
            }
        }
        return null;
    }

    /** 노선별 무방향 이웃 관계. 역 이름은 Segment 에 이미 정규화돼 있다. */
    static Map<String, Map<String, Set<String>>> adjacency(List<Segment> segments) {
        Map<String, Map<String, Set<String>>> adjacency = new LinkedHashMap<>();
        for (Segment s : segments) {
            Map<String, Set<String>> line = adjacency.computeIfAbsent(s.lineId(), k -> new LinkedHashMap<>());
            line.computeIfAbsent(s.fromName(), k -> new LinkedHashSet<>()).add(s.toName());
            line.computeIfAbsent(s.toName(), k -> new LinkedHashSet<>()).add(s.fromName());
        }
        return adjacency;
    }

    /** {@code start} 에서 {@code blocked} 를 지나지 않고 닿는 역 집합 (start 포함). */
    static Set<String> reachableWithout(Map<String, Set<String>> lineAdj, String start, String blocked) {
        Set<String> seen = new HashSet<>();
        Deque<String> queue = new ArrayDeque<>();
        seen.add(start);
        queue.add(start);
        while (!queue.isEmpty()) {
            String cur = queue.poll();
            for (String next : lineAdj.getOrDefault(cur, Set.of())) {
                if (!next.equals(blocked) && seen.add(next)) {
                    queue.add(next);
                }
            }
        }
        return seen;
    }

    /** "HHmmss"(앞 0 생략 허용) → 초. 없거나 "0" 이면 -1. 형식이 아니면 예외 대신 -1 로 두고 출발 없음으로 센다. */
    static int parseHms(String text) {
        if (text == null) {
            return -1;
        }
        String t = text.trim();
        if (t.isEmpty() || "0".equals(t) || !t.chars().allMatch(Character::isDigit) || t.length() > 6) {
            return -1;
        }
        String padded = "0".repeat(6 - t.length()) + t;
        int h = Integer.parseInt(padded.substring(0, 2));
        int m = Integer.parseInt(padded.substring(2, 4));
        int s = Integer.parseInt(padded.substring(4, 6));
        if (m >= 60 || s >= 60 || h >= 48) {
            return -1;
        }
        return h * 3600 + m * 60 + s;
    }

    /** TAGO dailyTypeCode 01 평일 · 02 토 · 03 일(공휴일) → edge_time.dow_type 0·1·2. 모르면 -1. */
    static int dowOf(String code) {
        if (code == null) {
            return -1;
        }
        return switch (code.trim()) {
            case "01", "1" -> 0;
            case "02", "2" -> 1;
            case "03", "3" -> 2;
            default -> -1;
        };
    }

    private static String orientationKey(Row row) {
        return row.lineId() + "|" + row.station() + "|" + row.upDown();
    }

    private static String majority(Map<String, Integer> counts) {
        if (counts == null || counts.isEmpty()) {
            return null;
        }
        return counts.entrySet().stream().max(Map.Entry.comparingByValue()).map(Map.Entry::getKey).orElse(null);
    }

    private static void count(Map<String, Integer> map, String key) {
        map.merge(key, 1, Integer::sum);
    }

    private static String value(Map<String, String> row, String key) {
        String v = row.get(key);
        return v == null ? "" : v.trim();
    }
}
