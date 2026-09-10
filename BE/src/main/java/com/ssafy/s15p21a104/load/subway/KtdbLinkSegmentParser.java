package com.ssafy.s15p21a104.load.subway;

import com.ssafy.s15p21a104.load.Coords;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * KTDB 철도망 링크(data/railgeometry/ktdb-rail-link_2024.csv, 63 에서 도입한 원천을 읽기만 한다) → 시각표가 없는 노선의 구간.
 * 링크 하나가 인접 역 한 쌍이고 {@code length_km} 가 선로 거리다. 한 방향만 있으므로 무방향 {@link Segment} 로 만들어 빌더가 양방향 엣지를 만든다.
 * 소요시간은 노선별 표정속도({@link LineSpeeds})로 추정하고 source='avg' 로 표시한다 — 시각표가 생기면 같은 키를 timetable 이 덮는다.
 * <p>
 * 노드 이름은 "판교역(신분당)" 꼴이라 괄호와 끝의 '역'을 뗀다. 이름이 "분기…" 인 노드는 역이 아닌 분기점(수색직결선·용산삼각선)이라
 * 같은 노선의 앞뒤 링크를 이어 거리를 합친다. 서비스 노선명이 비어 있는 물리 링크(경춘선 광운대 지선 = 망우선)는 예외 표로 노선을 붙인다.
 * 국가철도공단 역간거리 파일 대신 이 원천을 쓰는 이유는 그 파일의 앞·뒤 거리 열이 뒤섞여 있기 때문이다(경의중앙 76쌍 중 47 불일치).
 */
public final class KtdbLinkSegmentParser {

    /** 아주 짧은 구간이 0초가 되지 않게 하는 하한. */
    static final int MIN_TRAVEL_SEC = 30;
    /** 같은 (노선, 역 쌍)에 링크가 둘일 때 거리 차이가 이 이상이면 경고 (상봉역(경춘)·상봉역(일반)처럼 노드가 갈라진 경우). */
    static final int DUPLICATE_TOLERANCE_M = 100;
    private static final String JUNCTION_PREFIX = "분기";

    private final StationNameNormalizer normalizer;
    private final LineSpeeds speeds;
    private final Map<String, LinkOverride> lineOverrides;
    private final List<String> warnings = new ArrayList<>();
    private final Map<String, Set<String>> stationsByLine = new LinkedHashMap<>();

    /**
     * conf/ktdb-link-overrides.csv 의 한 행.
     *
     * @param lineIds 이 (출발역, 도착역) 링크가 속하는 서비스 노선
     * @param meters  KTDB 에 링크 자체가 없을 때 만들어 넣을 거리(m). null 이면 KTDB 의 서비스 노선명 없는 링크에 노선만 붙인다
     */
    public record LinkOverride(List<String> lineIds, Integer meters) {
        public LinkOverride {
            lineIds = List.copyOf(lineIds);
        }
    }

    /**
     * @param lineOverrides "출발역|도착역"(정규화 표기) → 예외. 서비스 노선명이 비어 있는 링크에 노선을 붙이거나(광운대 지선), KTDB 에 없는 링크를 더한다(가좌~신촌)
     */
    public KtdbLinkSegmentParser(StationNameNormalizer normalizer, LineSpeeds speeds, Map<String, LinkOverride> lineOverrides) {
        this.normalizer = normalizer;
        this.speeds = speeds;
        this.lineOverrides = Map.copyOf(lineOverrides);
    }

    /**
     * @param nodeRows ktdb-rail-node 행 (node_id, station_name_raw)
     * @param linkRows ktdb-rail-link 행 (from_node_id, to_node_id, line_name_raw, length_km)
     * @param lineIds  대상 노선. 비어 있으면 line_id 로 바꿀 수 있는 노선 전부
     */
    public List<Segment> parse(List<Map<String, String>> nodeRows, List<Map<String, String>> linkRows, Set<String> lineIds) {
        warnings.clear();
        stationsByLine.clear();
        Map<String, String> keyOf = new HashMap<>();
        Map<String, String> rawOf = new HashMap<>();
        for (Map<String, String> row : nodeRows) {
            String id = value(row, "node_id");
            String raw = value(row, "station_name_raw");
            if (id.isEmpty()) {
                continue;
            }
            rawOf.put(id, raw);
            keyOf.put(id, raw.startsWith(JUNCTION_PREFIX) ? junctionKey(id) : normalizer.normalizeStation(raw));
        }

        Map<String, LineGraph> graphs = new LinkedHashMap<>();
        for (Map<String, String> row : linkRows) {
            String from = keyOf.get(value(row, "from_node_id"));
            String to = keyOf.get(value(row, "to_node_id"));
            List<String> lines = linesOf(row, from, to);
            if (lines.isEmpty()) {
                continue;
            }
            String label = value(row, "line_name_raw") + " " + display(from, rawOf) + "→" + display(to, rawOf);
            if (from == null || to == null) {
                warnings.add("노드를 모르는 링크: " + label);
                continue;
            }
            if (from.equals(to)) {
                warnings.add("출발과 도착이 같은 링크: " + label);
                continue;
            }
            Double km;
            try {
                km = Coords.parseOrNull(row.get("length_km"));
            } catch (NumberFormatException e) {
                km = null;
            }
            if (km == null || km <= 0) {
                warnings.add("거리가 없거나 0 이하인 링크: " + label + " (" + row.get("length_km") + ")");
                continue;
            }
            int meters = (int) Math.round(km * 1000);
            for (String line : lines) {
                if (!lineIds.isEmpty() && !lineIds.contains(line)) {
                    continue;
                }
                graphs.computeIfAbsent(line, k -> new LineGraph()).addEdge(from, to, meters, line, rawOf);
            }
        }

        // KTDB 에 링크 자체가 없는 구간(예외 표에 거리가 있는 행)을 더한다. 이미 링크가 있으면 KTDB 값을 두고 경고만 남긴다
        for (Map.Entry<String, LinkOverride> e : lineOverrides.entrySet()) {
            if (e.getValue().meters() == null) {
                continue;
            }
            String[] ends = e.getKey().split("\\|", 2);
            for (String line : e.getValue().lineIds()) {
                if (!lineIds.isEmpty() && !lineIds.contains(line)) {
                    continue;
                }
                LineGraph g = graphs.computeIfAbsent(line, k -> new LineGraph());
                if (g.hasEdge(ends[0], ends[1])) {
                    warnings.add("예외 표의 " + ends[0] + "–" + ends[1] + " (" + LineCodes.nameOf(line) + ") 은 KTDB 에 링크가 이미 있어 예외 표 거리 "
                            + e.getValue().meters() + " m 를 무시하고 KTDB 값 " + g.meters(ends[0], ends[1]) + " m 를 쓴다");
                    continue;
                }
                g.addEdge(ends[0], ends[1], e.getValue().meters(), line, rawOf);
            }
        }

        List<Segment> out = new ArrayList<>();
        for (Map.Entry<String, LineGraph> e : graphs.entrySet()) {
            String line = e.getKey();
            LineGraph g = e.getValue();
            g.contractJunctions(line, rawOf);
            Set<String> stations = new LinkedHashSet<>();
            for (String[] pair : g.pairsInOrder()) {
                int meters = g.meters(pair[0], pair[1]);
                int travelSec = Math.max(MIN_TRAVEL_SEC, (int) Math.round(meters / speeds.speedOf(line)));
                out.add(new Segment(line, pair[0], pair[1], travelSec, meters, "avg"));
                stations.add(pair[0]);
                stations.add(pair[1]);
            }
            if (!stations.isEmpty()) {
                stationsByLine.put(line, stations);
            }
        }
        return out;
    }

    /** 마지막 parse 가 만든 노선별 역 이름 집합. 전체노선 파일의 역 목록과 대조하는 데 쓴다. */
    public Map<String, Set<String>> stationsByLine() {
        Map<String, Set<String>> copy = new LinkedHashMap<>();
        stationsByLine.forEach((k, v) -> copy.put(k, Set.copyOf(v)));
        return copy;
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    /** 서비스 노선명 → line_id, 없으면 (출발|도착) 예외 표. 둘 다 없으면 빈 목록 — 수도권 밖·모르는 노선은 조용히 건너뛴다. */
    private List<String> linesOf(Map<String, String> row, String from, String to) {
        Optional<String> byName = LineCodes.fromKtdbServiceName(value(row, "line_name_raw"));
        if (byName.isPresent()) {
            return List.of(byName.get());
        }
        if (from == null || to == null) {
            return List.of();
        }
        LinkOverride override = lineOverrides.get(from + "|" + to);
        if (override == null) {
            override = lineOverrides.get(to + "|" + from);
        }
        return override == null ? List.of() : override.lineIds();
    }

    private static String junctionKey(String nodeId) {
        return "#" + nodeId;
    }

    private static boolean isJunction(String key) {
        return key.startsWith("#");
    }

    private static String display(String key, Map<String, String> rawOf) {
        if (key == null) {
            return "?";
        }
        return isJunction(key) ? rawOf.getOrDefault(key.substring(1), key) : key;
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }

    /** 한 노선의 무방향 인접 그래프. 처음 본 링크 방향을 기억해 출력 순서를 원천대로 유지한다. */
    private final class LineGraph {
        private final Map<String, Map<String, Integer>> adjacency = new LinkedHashMap<>();
        private final Map<String, String[]> firstDirection = new LinkedHashMap<>();

        void addEdge(String from, String to, int meters, String line, Map<String, String> rawOf) {
            String pair = pairKey(from, to);
            Integer existing = adjacency.getOrDefault(from, Map.of()).get(to);
            if (existing != null) {
                if (Math.abs(existing - meters) > DUPLICATE_TOLERANCE_M) {
                    warnings.add("같은 구간 링크의 거리가 다름: " + LineCodes.nameOf(line) + " " + display(from, rawOf) + "–" + display(to, rawOf)
                            + " " + existing + " m vs " + meters + " m — 첫 값 유지");
                }
                return;
            }
            adjacency.computeIfAbsent(from, k -> new LinkedHashMap<>()).put(to, meters);
            adjacency.computeIfAbsent(to, k -> new LinkedHashMap<>()).put(from, meters);
            firstDirection.putIfAbsent(pair, new String[] {from, to});
        }

        /** 분기 노드를 앞뒤 역 사이의 한 구간으로 접는다. 링크가 정확히 둘 걸린 분기만 접을 수 있고, 아니면 버리고 경고한다. */
        void contractJunctions(String line, Map<String, String> rawOf) {
            boolean changed = true;
            while (changed) {
                changed = false;
                for (String key : new ArrayList<>(adjacency.keySet())) {
                    if (!isJunction(key)) {
                        continue;
                    }
                    Map<String, Integer> neighbors = adjacency.get(key);
                    if (neighbors.size() == 2) {
                        List<String> ends = new ArrayList<>(neighbors.keySet());
                        int meters = neighbors.get(ends.get(0)) + neighbors.get(ends.get(1));
                        removeNode(key);
                        addEdge(ends.get(0), ends.get(1), meters, line, rawOf);
                    } else {
                        warnings.add("분기 노드 '" + display(key, rawOf) + "' (" + LineCodes.nameOf(line) + ") 에 링크 " + neighbors.size()
                                + "개 — 어느 쪽을 이을지 몰라 버림");
                        removeNode(key);
                    }
                    changed = true;
                    break;
                }
            }
        }

        private void removeNode(String key) {
            for (String neighbor : new ArrayList<>(adjacency.getOrDefault(key, Map.of()).keySet())) {
                adjacency.get(neighbor).remove(key);
                if (adjacency.get(neighbor).isEmpty()) {
                    adjacency.remove(neighbor);
                }
                firstDirection.remove(pairKey(key, neighbor));
            }
            adjacency.remove(key);
        }

        List<String[]> pairsInOrder() {
            List<String[]> out = new ArrayList<>();
            for (String[] pair : firstDirection.values()) {
                if (adjacency.containsKey(pair[0]) && adjacency.get(pair[0]).containsKey(pair[1])) {
                    out.add(pair);
                }
            }
            return out;
        }

        int meters(String from, String to) {
            return adjacency.get(from).get(to);
        }

        boolean hasEdge(String from, String to) {
            return adjacency.containsKey(from) && adjacency.get(from).containsKey(to);
        }

        private String pairKey(String a, String b) {
            return a.compareTo(b) <= 0 ? a + "|" + b : b + "|" + a;
        }
    }
}
