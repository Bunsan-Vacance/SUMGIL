package com.ssafy.s15p21a104.domain.route.finder.raptor;

import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bike.BikeRentalEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteStopsReader;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * RAPTOR 프로토타입 실형상 스케일 테스트 — 서버 기동과 같은 원천(버스 노선 CSV·역 좌표 CSV·
 * 대여소·정류장)으로 노선·연결을 조립해 prod와 같은 OD의 탐색 시간을 잰다.
 *
 * <p>AC(4부 §5): BUS 포함 탐색 1초 내. 지하철은 좌표 CSV의 (호선, 순번) 체인으로 양방향 구성,
 * 버스는 원천 CSV 그대로. 승차 대기는 D1 결정 전이라 0으로 둔다(headway 미적재).
 */
class RaptorRealShapeScaleTest {

    private static final String COORDS = "data/subway/seoulmetro-station-coords_20250814.csv";
    private static final String BUS_STOPS = "data/bus/seoul-bus-stops_20260902.csv";
    private static final String BIKE_STATIONS = "data/bike/seoul-bike-stations_202606.csv";

    private static final double BUS_METERS_PER_SEC = 14_000.0 / 3600.0;
    private static final double SUBWAY_METERS_PER_SEC = 35_000.0 / 3600.0;

    @Test
    @DisplayName("실형상: 222→151 / 222→221 — RAPTOR 탐색 시간 기록 (1초 내)")
    void 실형상_탐색시간() throws IOException {
        long buildStart = System.nanoTime();
        List<RaptorFinder.Route> routes = new ArrayList<>();
        routes.addAll(busRoutes());
        Map<Integer, List<String[]>> subwayRows = new LinkedHashMap<>();
        Map<String, BikeEdgeBuilder.Stop> stations = new LinkedHashMap<>();
        Map<String, BikeEdgeBuilder.Stop> busStops = new LinkedHashMap<>();
        Map<String, BikeEdgeBuilder.Stop> rentals = new LinkedHashMap<>();
        readCsv(COORDS, cells -> {
            if (cells.length > 6) {
                addStop(stations, cells[2], cells[4], cells[5]);
                Integer line = parseInt(cells[1]);
                if (line != null) {
                    subwayRows.computeIfAbsent(line, key -> new ArrayList<>()).add(cells);
                }
            }
        });
        readCsv(BUS_STOPS, cells -> {
            if (cells.length > 4) {
                addStop(busStops, cells[0], cells[4], cells[3]);
            }
        });
        readCsv(BIKE_STATIONS, cells -> {
            if (cells.length > 5) {
                addStop(rentals, cells[0], cells[4], cells[5]);
            }
        });
        routes.addAll(subwayRoutes(subwayRows));

        List<RaptorFinder.Connection> connections = new ArrayList<>();
        for (Edge edge : WalkEdgeBuilder.build(stations, rentals, busStops)) {
            connections.add(new RaptorFinder.Connection(
                    edge.fromNode(), edge.toNode(), edge.travelSec(), TravelMode.WALK));
        }
        for (Edge edge : BikeRentalEdgeBuilder.build(rentals)) {
            connections.add(new RaptorFinder.Connection(
                    edge.fromNode(), edge.toNode(), edge.travelSec(), TravelMode.BIKE));
        }
        long buildMs = (System.nanoTime() - buildStart) / 1_000_000;
        int totalStops = routes.stream().mapToInt(route -> route.stops().size()).sum();
        System.out.printf("raptor routes=%d stops=%d connections=%d build=%dms%n",
                routes.size(), totalStops, connections.size(), buildMs);

        RaptorFinder finder = new RaptorFinder(routes, connections);
        String[][] ods = {{"222", "151"}, {"222", "221"}, {"221", "2734"}};
        for (String[] od : ods) {
            finder.find(od[0], od[1], Map.of(od[0], 0), Map.of(od[1], 0), 4, false); // 워밍업
            long start = System.nanoTime();
            List<RaptorFinder.Journey> journeys = finder.find(
                    od[0], od[1], Map.of(od[0], 0), Map.of(od[1], 0), 4, false);
            long ms = (System.nanoTime() - start) / 1_000_000;
            System.out.printf("raptor %s->%s: %dms journeys=%d%n", od[0], od[1], ms, journeys.size());
            for (RaptorFinder.Journey journey : journeys) {
                System.out.printf("  total=%ds transfers=%d legs=%d%n",
                        journey.totalSec(), journey.transfers(), journey.legs().size());
                for (RaptorFinder.Leg leg : journey.legs()) {
                    System.out.printf("    %s(%s) %s->%s %ds→%ds%n", leg.mode(), leg.routeId(),
                            leg.from(), leg.to(), leg.boardSec(), leg.alightSec());
                }
            }
            assertTrue(!journeys.isEmpty(), od[0] + "->" + od[1] + " journey 없음");
            assertTrue(ms < 1000, od[0] + "->" + od[1] + " 1초 초과: " + ms + "ms");
        }
    }

    private static List<RaptorFinder.Route> busRoutes() throws IOException {
        List<RaptorFinder.Route> routes = new ArrayList<>();
        for (Map.Entry<String, List<BusEdgeBuilder.RouteStop>> entry
                : BusRouteStopsReader.read().entrySet()) {
            List<BusEdgeBuilder.RouteStop> stops = new ArrayList<>(entry.getValue());
            stops.sort(Comparator.comparing(BusEdgeBuilder.RouteStop::seq,
                    Comparator.nullsLast(Integer::compareTo)));
            List<String> ids = new ArrayList<>();
            List<Integer> secs = new ArrayList<>();
            int part = 0;
            BusEdgeBuilder.RouteStop prev = null;
            for (BusEdgeBuilder.RouteStop stop : stops) {
                if (stop.lat() == null || stop.lng() == null) {
                    part = flush(routes, entry.getKey(), part, ids, secs);
                    prev = null;
                    continue;
                }
                if (prev != null) {
                    secs.add(Math.max(1, (int) Math.round(distanceM(prev.lat(), prev.lng(),
                            stop.lat(), stop.lng()) / BUS_METERS_PER_SEC)));
                }
                ids.add(stop.stopId());
                prev = stop;
            }
            flush(routes, entry.getKey(), part, ids, secs);
        }
        return routes;
    }

    /** 체인 하나를 노선으로 확정. 2정류장 미만이면 버린다. 반환 = 다음 part 번호. */
    private static int flush(List<RaptorFinder.Route> routes, String routeId, int part,
                             List<String> ids, List<Integer> secs) {
        if (ids.size() >= 2 && secs.size() == ids.size() - 1) {
            String id = part == 0 ? routeId : routeId + "-" + part;
            routes.add(new RaptorFinder.Route(id, TravelMode.BUS, List.copyOf(ids),
                    secs.stream().mapToInt(Integer::intValue).toArray(), 0));
            part++;
        }
        ids.clear();
        secs.clear();
        return part;
    }

    /** 좌표 CSV의 (호선, 순번) 체인을 양방향 노선으로. edge_time 실측 대체(위상 동일, 소요 근사). */
    private static List<RaptorFinder.Route> subwayRoutes(Map<Integer, List<String[]>> rowsByLine) {
        List<RaptorFinder.Route> routes = new ArrayList<>();
        for (Map.Entry<Integer, List<String[]>> entry : rowsByLine.entrySet()) {
            List<String[]> rows = new ArrayList<>(entry.getValue());
            rows.sort(Comparator.comparingInt(row -> {
                Integer seq = parseInt(row[0]);
                return seq == null ? Integer.MAX_VALUE : seq;
            }));
            // 좌표 있고 연속 중복 없는 정류장만 남긴다.
            List<String[]> filtered = new ArrayList<>();
            for (String[] row : rows) {
                Double lat = parseDouble(row[4]);
                Double lng = parseDouble(row[5]);
                if (lat == null || lng == null) {
                    continue;
                }
                if (!filtered.isEmpty() && filtered.get(filtered.size() - 1)[2].trim()
                        .equals(row[2].trim())) {
                    continue;
                }
                filtered.add(row);
            }
            if (filtered.size() < 2) {
                continue;
            }
            List<String> ids = new ArrayList<>();
            List<Integer> secs = new ArrayList<>();
            for (int i = 0; i < filtered.size(); i++) {
                ids.add(filtered.get(i)[2].trim());
                if (i > 0) {
                    String[] from = filtered.get(i - 1);
                    String[] to = filtered.get(i);
                    secs.add(Math.max(30, (int) Math.round(distanceM(
                            parseDouble(from[4]), parseDouble(from[5]),
                            parseDouble(to[4]), parseDouble(to[5])) / SUBWAY_METERS_PER_SEC)));
                }
            }
            String lineId = "L" + entry.getKey();
            routes.add(new RaptorFinder.Route(lineId, TravelMode.SUBWAY, List.copyOf(ids),
                    secs.stream().mapToInt(Integer::intValue).toArray(), 0));
            List<String> reversedIds = new ArrayList<>(ids);
            java.util.Collections.reverse(reversedIds);
            int[] reversedSecs = new int[secs.size()];
            for (int i = 0; i < secs.size(); i++) {
                reversedSecs[i] = secs.get(secs.size() - 1 - i);
            }
            routes.add(new RaptorFinder.Route(lineId + "-down", TravelMode.SUBWAY,
                    List.copyOf(reversedIds), reversedSecs, 0));
        }
        return routes;
    }

    private static double distanceM(double lat1, double lng1, double lat2, double lng2) {
        double dLat = Math.toRadians(lat2 - lat1);
        double dLng = Math.toRadians(lng2 - lng1);
        double h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(lat1)) * Math.cos(Math.toRadians(lat2))
                * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return 2 * 6_371_000.0 * Math.asin(Math.sqrt(h));
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
        try (InputStream in = RaptorRealShapeScaleTest.class.getClassLoader()
                .getResourceAsStream(resourcePath)) {
            if (in == null) {
                throw new IOException("원천 없음: " + resourcePath);
            }
            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(in, StandardCharsets.UTF_8));
            reader.readLine();
            String line;
            while ((line = reader.readLine()) != null) {
                row.accept(line.split(",", -1));
            }
        }
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
