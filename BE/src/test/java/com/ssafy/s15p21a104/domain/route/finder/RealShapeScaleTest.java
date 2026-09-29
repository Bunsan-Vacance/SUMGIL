package com.ssafy.s15p21a104.domain.route.finder;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bike.BikeRentalEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteStopsReader;
import com.ssafy.s15p21a104.domain.route.dto.request.CoordinateRouteSearchRequest;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePlaceRequest;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.service.RouteSearchService;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
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
import java.util.Optional;
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

    @Test
    @DisplayName("실형상: 대림 도보권(집)→신도림 좌표 검색 — prod 500 재현")
    void 실형상_좌표검색() throws IOException {
        RouteGraph graph = buildGraph();
        BusRouteIndex index = BusRouteIndex.build(BusRouteStopsReader.read());
        Infos infos = buildInfos();

        RouteSearchService service = serviceFor(graph, index, infos);

        long start = System.nanoTime();
        List<RouteSearchResponse> responses = service.searchByCoordinate(
                new CoordinateRouteSearchRequest(
                        new RoutePlaceRequest(37.4895, 126.898, "home"),
                        new RoutePlaceRequest(37.508815, 126.891222, "sindorim"),
                        null, null, null));
        long ms = (System.nanoTime() - start) / 1_000_000;
        System.out.printf("coord responses=%d %dms%n", responses.size(), ms);
        int i = 0;
        for (RouteSearchResponse response : responses) {
            i++;
            StringBuilder legs = new StringBuilder();
            response.legs().forEach(leg -> legs.append(leg.mode()).append('(').append(leg.routeId())
                    .append(") ").append(leg.fromNodeId()).append('>').append(leg.toNodeId())
                    .append(" [").append(String.format("%.1f", leg.minutes())).append("m] | "));
            System.out.printf("[%d] %s total=%.2fm transfers=%d :: %s%n",
                    i, response.routeType(), response.totalMinutes(), response.transferCount(), legs);
        }

        // prod 500 재현 시도: 대림(233)→신도림(234) 역 검색 (좌표 아님)
        List<RouteSearchResponse> stationResponses = service.search("233", "234", null, null, null);
        System.out.printf("station 233->234 responses=%d%n", stationResponses.size());
        for (RouteSearchResponse response : stationResponses) {
            StringBuilder legs = new StringBuilder();
            response.legs().forEach(leg -> legs.append(leg.mode()).append('(').append(leg.routeId())
                    .append(") ").append(leg.fromNodeId()).append('>').append(leg.toNodeId())
                    .append(" | "));
            System.out.printf("  %s total=%.2fm :: %s%n",
                    response.routeType(), response.totalMinutes(), legs);
        }
    }

    @Test
    @DisplayName("실형상: 역삼 멀티캠퍼스→세종대 — 수단 추가가 기존 경로를 지우면 안 된다(빈 결과 회귀)")
    void 실형상_역삼세종대_수단추가_빈결과_회귀() throws IOException {
        RouteGraph graph = buildGraph();
        BusRouteIndex index = BusRouteIndex.build(BusRouteStopsReader.read());
        Infos infos = buildInfos();
        RouteSearchService service = serviceFor(graph, index, infos);
        RoutePlaceRequest origin = new RoutePlaceRequest(37.50162, 127.03944, "멀티캠퍼스 역삼");
        RoutePlaceRequest dest = new RoutePlaceRequest(37.5514705, 127.073884, "세종대학교");

        assertAtLeastOne(service, origin, dest,
                List.of(TravelMode.WALK, TravelMode.SUBWAY), "WALK,SUBWAY");
        assertAtLeastOne(service, origin, dest,
                List.of(TravelMode.WALK, TravelMode.BUS, TravelMode.SUBWAY), "WALK,BUS,SUBWAY");
        assertAtLeastOne(service, origin, dest,
                List.of(TravelMode.WALK, TravelMode.BIKE, TravelMode.BUS, TravelMode.SUBWAY), "WALK,BIKE,BUS,SUBWAY");
    }

    private static void assertAtLeastOne(RouteSearchService service, RoutePlaceRequest origin,
                                         RoutePlaceRequest dest, List<TravelMode> modes, String label) {
        long start = System.nanoTime();
        List<RouteSearchResponse> responses = service.searchByCoordinate(
                new CoordinateRouteSearchRequest(origin, dest, modes, null, null));
        long ms = (System.nanoTime() - start) / 1_000_000;
        System.out.printf("[%s] responses=%d %dms%n", label, responses.size(), ms);
        assertTrue(!responses.isEmpty(), label + " 결과가 0건 — 수단 추가가 기존 경로를 지웠다");
    }

    private static RouteSearchService serviceFor(RouteGraph graph, BusRouteIndex index, Infos infos) {
        com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry registry =
                mock(com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry.class);
        lenient().when(registry.graph()).thenReturn(graph);
        lenient().when(registry.graphFor(anyInt(), anyInt())).thenReturn(graph);
        lenient().when(registry.stationInfos()).thenReturn(Map.copyOf(infos.all));
        lenient().when(registry.stationIds()).thenReturn(Set.copyOf(infos.stationIds));
        lenient().when(registry.rentalIds()).thenReturn(Set.copyOf(infos.rentalIds));
        lenient().when(registry.bikeStock()).thenReturn(Map.of());
        lenient().when(registry.transferTimes()).thenReturn(Map.of());
        lenient().when(registry.busRouteIndex()).thenReturn(index);

        StationRepository stationRepository = mock(StationRepository.class);
        lenient().when(stationRepository.findById(anyString())).thenAnswer(invocation ->
                Optional.of(RouteTestFixtures.mockStation(invocation.getArgument(0), "역")));

        return new RouteSearchService(
                stationRepository, registry, new TransferRule(180),
                new RailGeometryRegistry(null, null),
                RouteTestFixtures.noopWalkGeometryRegistry(),
                RouteTestFixtures.noopBikeGeometryRegistry(),
                RouteTestFixtures.noopRouteLineRepository(),
                RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository(),
                RouteTestFixtures.noopCongestionPredRepository());
    }

    /** 역·정류장·대여소 표시 정보(좌표 포함) — registry.stationInfos 대응. */
    private static Infos buildInfos() throws IOException {        Infos infos = new Infos();
        readCsv(COORDS, cells -> {
            if (cells.length > 6) {
                String id = cells[2].trim();
                Double lat = parseDouble(cells[4]);
                Double lng = parseDouble(cells[5]);
                if (!id.isEmpty() && lat != null && lng != null) {
                    infos.all.putIfAbsent(id, new RouteMapper.StationInfo(id, cells[3], lat, lng));
                    infos.stationIds.add(id);
                }
            }
        });
        readCsv(BUS_STOPS, cells -> {
            if (cells.length > 4) {
                String id = cells[0].trim();
                Double lat = parseDouble(cells[4]);
                Double lng = parseDouble(cells[3]);
                if (!id.isEmpty() && lat != null && lng != null) {
                    infos.all.putIfAbsent(id, new RouteMapper.StationInfo(id, cells[2], lat, lng));
                }
            }
        });
        readCsv(BIKE_STATIONS, cells -> {
            if (cells.length > 5) {
                String id = cells[0].trim();
                Double lat = parseDouble(cells[4]);
                Double lng = parseDouble(cells[5]);
                if (!id.isEmpty() && lat != null && lng != null) {
                    infos.all.putIfAbsent(id, new RouteMapper.StationInfo(id, cells[1], lat, lng));
                    infos.rentalIds.add(id);
                }
            }
        });
        return infos;
    }

    private static final class Infos {
        final Map<String, RouteMapper.StationInfo> all = new LinkedHashMap<>();
        final Set<String> stationIds = new LinkedHashSet<>();
        final Set<String> rentalIds = new LinkedHashSet<>();
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
