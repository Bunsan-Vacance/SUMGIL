package com.ssafy.s15p21a104.domain.route.finder;

import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bike.BikeRentalEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteStopsReader;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Consumer;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 실그래프 형상 재현 규모 테스트(S15P21A104-215 후속).
 *
 * <p>서버 기동 그래프와 같은 원천(정류장·노선·대여소 CSV + 좌표)으로 DB 없이 조립한다.
 * 지하철 엣지(`edge_time`)는 DB 산출물이라 여기선 뺀다 — 폭증의 본체인 버스 corridor와
 * 도보 연결망의 형상을 같은 크기로 재현하는 것이 목적이다(prod 실측: 222→221 8s,
 * 222→151 40s+).
 */
class RealShapeScaleTest {

    private static final String COORDS = "data/subway/seoulmetro-station-coords_20250814.csv";
    private static final String BUS_STOPS = "data/bus/seoul-bus-stops_20260902.csv";
    private static final String BIKE_STATIONS = "data/bike/seoul-bike-stations_202606.csv";

    @Test
    @DisplayName("실형상: prod와 같은 OD로 findK(10) 시간을 기록한다")
    void 실형상_findK_기록() throws IOException {
        long buildStart = System.nanoTime();
        RouteGraph graph = buildGraph();
        long buildMs = (System.nanoTime() - buildStart) / 1_000_000;
        BusRouteIndex index = BusRouteIndex.build(BusRouteStopsReader.read());
        System.out.printf("real-shape graph: nodes=%d edges=%d build=%dms%n",
                graph.nodeCount(), graph.edgeCount(), buildMs);

        KShortestPathFinder finder = new KShortestPathFinder(new TransferRule(180), index);
        String[][] ods = {{"222", "221"}, {"222", "151"}};
        for (String[] od : ods) {
            finder.findK(graph, od[0], od[1], 1); // 워밍업
            long start = System.nanoTime();
            List<FoundPath> paths = finder.findK(graph, od[0], od[1], 10);
            long ms = (System.nanoTime() - start) / 1_000_000;
            System.out.printf("findK(10) %s->%s: %dms paths=%d%n", od[0], od[1], ms, paths.size());
            for (FoundPath path : paths) {
                System.out.printf("  total=%ds transfers=%d edges=%d%n",
                        path.totalSec(), path.transferCount(), path.edges().size());
            }
        }
        assertTrue(graph.nodeCount() > 10_000, "실형상 그래프가 아니다");
    }

    /** 서버 기동 로더와 같은 원천으로 버스·도보·대여·지하철 엣지를 조립한다. */
    private static RouteGraph buildGraph() throws IOException {
        Map<String, BikeEdgeBuilder.Stop> stations = new LinkedHashMap<>();
        Map<String, BikeEdgeBuilder.Stop> busStops = new LinkedHashMap<>();
        Map<String, BikeEdgeBuilder.Stop> rentals = new LinkedHashMap<>();
        Map<Integer, List<String[]>> subwayRowsByLine = new LinkedHashMap<>();

        readCsv(COORDS, cells -> {
            if (cells.length > 6) {
                addStop(stations, cells[2], cells[4], cells[5]);
                Integer line = parseInt(cells[1]);
                if (line != null) {
                    subwayRowsByLine.computeIfAbsent(line, key -> new ArrayList<>()).add(cells);
                }
            }
        });
        readCsv(BUS_STOPS, cells -> {
            // X좌표=lng, Y좌표=lat (원천 컬럼 순서)
            if (cells.length > 4) {
                addStop(busStops, cells[0], cells[4], cells[3]);
            }
        });
        readCsv(BIKE_STATIONS, cells -> {
            if (cells.length > 5) {
                addStop(rentals, cells[0], cells[4], cells[5]);
            }
        });

        List<Edge> edges = new ArrayList<>();
        edges.addAll(subwayChainEdges(subwayRowsByLine));
        edges.addAll(WalkEdgeBuilder.build(stations, rentals, busStops));
        edges.addAll(BikeRentalEdgeBuilder.build(rentals));
        edges.addAll(BusEdgeBuilder.buildCorridors(BusRouteStopsReader.read()));

        Set<String> nodes = new LinkedHashSet<>();
        Map<String, List<Edge>> adjacency = new LinkedHashMap<>();
        Map<String, Set<String>> lines = new LinkedHashMap<>();
        for (Edge edge : edges) {
            nodes.add(edge.fromNode());
            nodes.add(edge.toNode());
            adjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>()).add(edge);
            lines.computeIfAbsent(edge.fromNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
            lines.computeIfAbsent(edge.toNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
        }
        return RouteGraph.of(nodes, adjacency, lines);
    }

    /**
     * 좌표 원천의 (호선, 순번)으로 노선 체인을 만든다. edge_time(DB 산출물) 대체용 근사 —
     * 위상(연결 순서)은 실제와 같고 소요만 직선거리/표정속도로 계산한다.
     */
    private static List<Edge> subwayChainEdges(Map<Integer, List<String[]>> rowsByLine) {
        List<Edge> edges = new ArrayList<>();
        for (Map.Entry<Integer, List<String[]>> entry : rowsByLine.entrySet()) {
            String routeId = "L" + entry.getKey();
            List<String[]> rows = new ArrayList<>(entry.getValue());
            rows.sort(java.util.Comparator.comparingInt(row -> {
                Integer seq = parseInt(row[0]);
                return seq == null ? Integer.MAX_VALUE : seq;
            }));
            for (int i = 0; i + 1 < rows.size(); i++) {
                String[] from = rows.get(i);
                String[] to = rows.get(i + 1);
                String fromId = from[2].trim();
                String toId = to[2].trim();
                Double fromLat = parseDouble(from[4]);
                Double fromLng = parseDouble(from[5]);
                Double toLat = parseDouble(to[4]);
                Double toLng = parseDouble(to[5]);
                if (fromId.equals(toId) || fromLat == null || toLat == null) {
                    continue;
                }
                int sec = Math.max(30, (int) Math.round(distanceM(fromLat, fromLng, toLat, toLng) / SUBWAY_METERS_PER_SEC));
                edges.add(new Edge(fromId, toId, routeId, sec, 0,
                        com.ssafy.s15p21a104.domain.route.entity.TravelMode.SUBWAY));
                edges.add(new Edge(toId, fromId, routeId, sec, 0,
                        com.ssafy.s15p21a104.domain.route.entity.TravelMode.SUBWAY));
            }
        }
        return edges;
    }

    /** 지하철 표정속도(m/s). 35km/h 근사. */
    private static final double SUBWAY_METERS_PER_SEC = 35_000.0 / 3600.0;

    private static double distanceM(double lat1, double lng1, double lat2, double lng2) {
        double dLat = Math.toRadians(lat2 - lat1);
        double dLng = Math.toRadians(lng2 - lng1);
        double h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(lat1)) * Math.cos(Math.toRadians(lat2))
                * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return 2 * 6_371_000.0 * Math.asin(Math.sqrt(h));
    }

    private static Integer parseInt(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.valueOf(value.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static void addStop(Map<String, BikeEdgeBuilder.Stop> target,
                                String id, String lat, String lng) {
        String key = id.trim();
        Double latValue = parseDouble(lat);
        Double lngValue = parseDouble(lng);
        if (key.isEmpty() || latValue == null || lngValue == null) {
            return;
        }
        target.putIfAbsent(key, new BikeEdgeBuilder.Stop(key, latValue, lngValue));
    }

    private static void readCsv(String resourcePath, Consumer<String[]> row) throws IOException {
        try (InputStream in = RealShapeScaleTest.class.getClassLoader()
                .getResourceAsStream(resourcePath)) {
            if (in == null) {
                throw new IOException("원천 없음: " + resourcePath);
            }
            BufferedReader reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
            reader.readLine(); // 헤더 스킵
            String line;
            while ((line = reader.readLine()) != null) {
                row.accept(line.split(",", -1));
            }
        }
    }

    private static Double parseDouble(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Double.valueOf(value.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
