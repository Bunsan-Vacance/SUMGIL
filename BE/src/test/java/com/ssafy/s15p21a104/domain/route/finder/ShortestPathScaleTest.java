package com.ssafy.s15p21a104.domain.route.finder;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-235 탐색 성능 규모 테스트(재현 테스트, AC4).
 *
 * <p>운영 규모·비율의 합성 그래프를 DB·Redis 없이 만든다. 난수 없이 결정적으로
 * 생성하므로 매 실행 같은 그래프이고, 지하철 9노선·버스 정류장 13,000·버스 노선 700의
 * 비율은 실제 그래프를 따른다(S15P21A104-234 인수 후 60초 초과 조건의 축소 재현).
 *
 * <p>출발·도착은 노선이 겹치는 버스 축 위에 둔다 — 회귀의 핵심인 "구간당 운행 노선
 * 겹침"을 만들고, Yen이 경로 정점마다 그래프를 재조립하는 비용을 드러낸다.
 */
class ShortestPathScaleTest {

    private static final int SUBWAY_LINES = 9;
    private static final int SUBWAY_STATIONS = 300;

    private static final int BUS_AXES = 40;
    private static final int BUS_STOPS = 325;

    /** 버스 노선 수 — 축 40개에 나눠 태운다. 구간당 운행 노선이 겹치게 한다. */
    private static final int BUS_ROUTES = 700;

    /** 노선 1개가 태우는 정류장 수(연속 구간). */
    private static final int ROUTE_SPAN = 160;

    private static final String ORIGIN = "B0_100";
    private static final String DEST = "B0_160";

    /**
     * 도달 불가 질량 정점망 — O/D와 분리해 두고 그래프 전수 스캔 비용만 키운다.
     * spur마다 그래프를 재조립하는 구현은 이 질량을 매번 훑고, 금지 집합 전달 구현은
     * 건너뛰므로 두 구현이 이 지점에서 갈린다.
     */
    private static final int DEAD_NODES = 20_000;

    private static final int[] DEAD_STRIDES = {7, 197, 1234, 7777, 9999};

    @Test
    @DisplayName("235: 운영 규모 합성 그래프 — 경로 탐색 시간을 기록한다")
    void t_운영규모_탐색_기록() {
        long buildStart = System.nanoTime();
        Synthetic synthetic = build();
        long buildMs = (System.nanoTime() - buildStart) / 1_000_000;

        RouteGraph graph = synthetic.graph();
        KShortestPathFinder finder = new KShortestPathFinder(new TransferRule(180), synthetic.index());

        System.out.printf("graph: nodes=%d edges=%d build=%dms%n",
                graph.nodeCount(), graph.edgeCount(), buildMs);

        // 워밍업 (JIT) 후 단일 탐색 3회
        finder.findK(graph, ORIGIN, DEST, 1);
        long singleMs = 0;
        for (int i = 0; i < 3; i++) {
            long t = System.nanoTime();
            finder.findK(graph, ORIGIN, DEST, 1);
            singleMs = (System.nanoTime() - t) / 1_000_000;
        }
        System.out.printf("findK(1)=%dms%n", singleMs);

        long findKStart = System.nanoTime();
        List<FoundPath> paths = finder.findK(graph, ORIGIN, DEST, 3);
        long findKMs = (System.nanoTime() - findKStart) / 1_000_000;
        System.out.printf("findK(3)=%dms paths=%d firstLen=%d lastLen=%d%n",
                findKMs, paths.size(),
                paths.isEmpty() ? -1 : paths.get(0).edges().size(),
                paths.isEmpty() ? -1 : paths.get(paths.size() - 1).edges().size());
        for (int i = 0; i < paths.size(); i++) {
            FoundPath path = paths.get(i);
            System.out.printf("path[%d]: total=%ds transfers=%d stations=%s%n",
                    i, path.totalSec(), path.transferCount(), String.join(">", path.stations()));
        }

        // Yen이 spur마다 수행하는 그래프 재조립 비용을 같은 연산으로 1회 측정한다
        long rebuildMs = measureRebuildPrimitive(graph);
        System.out.printf("rebuild-primitive(1회)=%dms%n", rebuildMs);

        assertTrue(paths.size() >= 1, "경로가 하나도 없으면 재현 그래프가 아니다");
        assertTrue(findKMs < 5000,
                "findK(3) 5초 초과 — spur 그래프 재조립 비용이 남아 있다 (실측 " + findKMs + "ms)");

        assertEquals(1200, paths.get(0).totalSec(), "최단 후보 소요가 바뀌었다 — 응답 동등 위반");
        assertEquals(0, paths.get(0).transferCount());
        List<String> expectedFirst = new ArrayList<>();
        for (int j = 100; j <= 160; j++) {
            expectedFirst.add(busStop(0, j));
        }
        assertEquals(expectedFirst, paths.get(0).stations(), "최단 후보 정점 순서가 바뀌었다");
    }

    /** Yen spur가 그래프를 재조립할 때 드는 비용을 같은 연산(전수 순회 + RouteGraph.of)으로 잰다. */
    private static long measureRebuildPrimitive(RouteGraph graph) {
        long start = System.nanoTime();
        Set<String> nodes = new LinkedHashSet<>(graph.nodes());
        Map<String, List<Edge>> adjacency = new LinkedHashMap<>();
        Map<String, Set<String>> lines = new LinkedHashMap<>();
        for (Edge edge : graph.edges()) {
            adjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>()).add(edge);
            lines.computeIfAbsent(edge.fromNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
            lines.computeIfAbsent(edge.toNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
        }
        RouteGraph rebuilt = RouteGraph.of(nodes, adjacency, lines);
        long elapsed = System.nanoTime() - start;
        assertTrue(rebuilt.nodeCount() > 0);
        return elapsed / 1_000_000;
    }

    private record Synthetic(RouteGraph graph, BusRouteIndex index) {
    }

    /** 운영 규모·비율의 합성 그래프 1개와 그 BUS 노선 인덱스를 만든다(결정적). */
    private static Synthetic build() {
        Set<String> nodes = new LinkedHashSet<>();
        Map<String, List<Edge>> adjacency = new LinkedHashMap<>();
        Map<String, Set<String>> lines = new LinkedHashMap<>();

        // 지하철 9노선 × 300역 — 노선별 연속 구간 양방향
        for (int l = 1; l <= SUBWAY_LINES; l++) {
            String routeId = "L" + l;
            for (int i = 0; i < SUBWAY_STATIONS; i++) {
                nodes.add("S" + l + "_" + i);
            }
            for (int i = 0; i + 1 < SUBWAY_STATIONS; i++) {
                String from = "S" + l + "_" + i;
                String to = "S" + l + "_" + (i + 1);
                add(adjacency, lines, new Edge(from, to, routeId, 60, 0, TravelMode.SUBWAY));
                add(adjacency, lines, new Edge(to, from, routeId, 60, 0, TravelMode.SUBWAY));
            }
        }

        // 버스 축 40개 × 정류장 325 — 인접 구간 양방향 1엣지(234 정규화)
        for (int a = 0; a < BUS_AXES; a++) {
            for (int j = 0; j < BUS_STOPS; j++) {
                nodes.add(busStop(a, j));
            }
            for (int j = 0; j + 1 < BUS_STOPS; j++) {
                String from = busStop(a, j);
                String to = busStop(a, j + 1);
                add(adjacency, lines, new Edge(from, to,
                        BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID, 20, 0, TravelMode.BUS));
                add(adjacency, lines, new Edge(to, from,
                        BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID, 20, 0, TravelMode.BUS));
            }
        }

        // 도보: 인접 축 같은 인덱스(정점당 2) + 같은 축 10칸 건너(정점당 2)
        for (int a = 0; a < BUS_AXES; a++) {
            int nextAxis = (a + 1) % BUS_AXES;
            for (int j = 0; j < BUS_STOPS; j += 10) {
                add(adjacency, lines, new Edge(busStop(a, j), busStop(nextAxis, j),
                        WalkEdgeBuilder.WALK_ROUTE_ID, 30, 0, TravelMode.WALK));
                add(adjacency, lines, new Edge(busStop(nextAxis, j), busStop(a, j),
                        WalkEdgeBuilder.WALK_ROUTE_ID, 30, 0, TravelMode.WALK));
            }
        }
        for (int a = 0; a < BUS_AXES; a++) {
            for (int j = 0; j + 10 < BUS_STOPS; j += 10) {
                add(adjacency, lines, new Edge(busStop(a, j), busStop(a, j + 10),
                        WalkEdgeBuilder.WALK_ROUTE_ID, 3000, 0, TravelMode.WALK));
                add(adjacency, lines, new Edge(busStop(a, j + 10), busStop(a, j),
                        WalkEdgeBuilder.WALK_ROUTE_ID, 3000, 0, TravelMode.WALK));
            }
        }

        // 지하철-버스 연결: 25칸마다 1개 (수단 간 대안 경로)
        for (int a = 0; a < BUS_AXES; a++) {
            int line = (a % SUBWAY_LINES) + 1;
            for (int j = 0; j < BUS_STOPS; j += 25) {
                String station = "S" + line + "_" + (j % SUBWAY_STATIONS);
                add(adjacency, lines, new Edge(busStop(a, j), station,
                        WalkEdgeBuilder.WALK_ROUTE_ID, 200, 0, TravelMode.WALK));
                add(adjacency, lines, new Edge(station, busStop(a, j),
                        WalkEdgeBuilder.WALK_ROUTE_ID, 200, 0, TravelMode.WALK));
            }
        }

        // 도달 불가 질량 정점망: O/D에서 닿지 않으므로 탐색은 안 가고, 재조립만 훑는다
        for (int i = 0; i < DEAD_NODES; i++) {
            String from = "D" + i;
            nodes.add(from);
            for (int stride : DEAD_STRIDES) {
                add(adjacency, lines, new Edge(from, "D" + ((i + stride) % DEAD_NODES),
                        "DL", 100, 0, TravelMode.SUBWAY));
            }
        }

        // 버스 노선 700개: 축에 나눠 태우고 연속 160칸 구간을 덮는다 (시작점은 결정적 분산)
        Map<String, List<BusEdgeBuilder.RouteStop>> routes = new LinkedHashMap<>();
        for (int k = 0; k < BUS_ROUTES; k++) {
            int axis = k % BUS_AXES;
            int start = (k * 17) % (BUS_STOPS - ROUTE_SPAN);
            List<BusEdgeBuilder.RouteStop> stops = new ArrayList<>();
            for (int s = 0; s <= ROUTE_SPAN; s++) {
                stops.add(new BusEdgeBuilder.RouteStop(busStop(axis, start + s), s + 1, 37.5, 127.0));
            }
            routes.put("R" + k, stops);
        }

        return new Synthetic(RouteGraph.of(nodes, adjacency, lines), BusRouteIndex.build(routes));
    }

    private static String busStop(int axis, int index) {
        return "B" + axis + "_" + index;
    }

    private static void add(Map<String, List<Edge>> adjacency, Map<String, Set<String>> lines,
                            Edge edge) {
        adjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>()).add(edge);
        lines.computeIfAbsent(edge.fromNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
        lines.computeIfAbsent(edge.toNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
    }
}
