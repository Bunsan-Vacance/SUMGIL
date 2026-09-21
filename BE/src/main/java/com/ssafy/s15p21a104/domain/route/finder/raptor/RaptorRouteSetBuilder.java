package com.ssafy.s15p21a104.domain.route.finder.raptor;

import com.ssafy.s15p21a104.domain.congestion.scoring.SubwayDirectionResolver;
import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bike.BikeRentalEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * RAPTOR 노선·연결 조립기(S15P21A104-217 ③) — 순수 로직, DB·Spring 비의존.
 *
 * <p>지하철: 슬롯 {@code edge_time} 행을 노선·방향별 순서 배열로 엮는다. 방향은
 * {@link SubwayDirectionResolver}(역번호 규칙)로 가르고, 규칙이 보류하는 반전 링크는
 * 체인 끝/시작에 붙이는 방식으로 해소한다. 순환선은 사이클을 두 바퀴로 펼쳐 한 바퀴
 * 이내의 순환이동을 표현한다.
 *
 * <p>버스: 노선별 경유 정류소 CSV(순번) 순서 그대로. 소요는 기존 산식(직선÷14km/h)을
 * 재사용한다. 승차 대기는 버스 headway 배선(218) 전까지 0.
 */
public final class RaptorRouteSetBuilder {

    private static final Logger log = LoggerFactory.getLogger(RaptorRouteSetBuilder.class);

    private RaptorRouteSetBuilder() {
    }

    /** 지하철 노선들을 방향별 순서 배열로. 연속 구간이 실제 행과 일치해야 한다(검증은 테스트). */
    public static List<RaptorFinder.Route> subwayRoutes(List<RouteEdgeRow> rows) {
        Map<String, List<RouteEdgeRow>> byLine = new LinkedHashMap<>();
        for (RouteEdgeRow row : rows) {
            byLine.computeIfAbsent(row.routeId(), key -> new ArrayList<>()).add(row);
        }
        List<RaptorFinder.Route> routes = new ArrayList<>();
        for (Map.Entry<String, List<RouteEdgeRow>> entry : byLine.entrySet()) {
            String lineId = entry.getKey();
            List<RouteEdgeRow> lineRows = entry.getValue();
            // 순환선(모든 정점 차수 2·양방향 완비)은 방향 규칙이 꼬이므로 사이클을 직접 걷는다.
            List<String> cycle = cycleOrder(lineRows);
            if (cycle != null) {
                RaptorFinder.Route forward = materializeCycle(lineId, cycle, lineRows);
                RaptorFinder.Route backward = materializeCycle(lineId + "-down", reverseCycle(cycle), lineRows);
                if (forward != null && backward != null) {
                    routes.add(backward);
                    routes.add(forward);
                    continue;
                }
                log.warn("순환선 조립 실패, 방향 체인으로 폴백: {}", lineId);
            }
            Map<String, List<Segment>> chains = new LinkedHashMap<>();
            List<RouteEdgeRow> unresolved = new ArrayList<>();
            for (RouteEdgeRow row : lineRows) {
                Optional<String> direction =
                        SubwayDirectionResolver.resolve(row.fromNode(), row.toNode(), lineId);
                if (direction.isPresent()) {
                    chains.computeIfAbsent(direction.get(), key -> new ArrayList<>())
                            .add(Segment.of(row));
                } else {
                    unresolved.add(row);
                }
            }
            // 체인 연결: from→to 인접 맵으로 시작점(진입 0)에서 걷는다.
            List<List<Segment>> ordered = new ArrayList<>();
            for (List<Segment> group : chains.values()) {
                ordered.add(chain(group, lineId));
            }
            // 규칙 보류 링크(반전 3개)는 체인 끝/시작에 붙인다. 못 붙이면 버린다(값을 지어내지 않음).
            for (RouteEdgeRow row : unresolved) {
                if (!attach(ordered, row)) {
                    log.debug("지하철 미해결 링크 버림: {} {}->{}", lineId, row.fromNode(), row.toNode());
                }
            }
            for (List<Segment> segments : ordered) {
                materialize(lineId, TravelMode.SUBWAY, segments, routes);
            }
        }
        return routes;
    }

    /**
     * 순환선이면 사이클 정점 순서를 돌려준다. 조건: 양방향 행이 완비되고(행 = 정점수×2)
     * 모든 정점의 무방향 차수가 2. 아니면 null.
     */
    private static List<String> cycleOrder(List<RouteEdgeRow> rows) {
        Map<String, java.util.LinkedHashSet<String>> neighbors = new LinkedHashMap<>();
        for (RouteEdgeRow row : rows) {
            neighbors.computeIfAbsent(row.fromNode(), key -> new java.util.LinkedHashSet<>())
                    .add(row.toNode());
            neighbors.computeIfAbsent(row.toNode(), key -> new java.util.LinkedHashSet<>())
                    .add(row.fromNode());
        }
        if (rows.size() != neighbors.size() * 2) {
            return null;
        }
        for (java.util.LinkedHashSet<String> neighbor : neighbors.values()) {
            if (neighbor.size() != 2) {
                return null;
            }
        }
        List<String> cycle = new ArrayList<>();
        String start = neighbors.keySet().iterator().next();
        String current = start;
        String previous = null;
        do {
            cycle.add(current);
            java.util.Iterator<String> iterator = neighbors.get(current).iterator();
            String next = iterator.next();
            if (next.equals(previous)) {
                next = iterator.next();
            }
            previous = current;
            current = next;
        } while (!current.equals(start) && cycle.size() <= neighbors.size());
        return cycle.size() == neighbors.size() ? cycle : null;
    }

    private static List<String> reverseCycle(List<String> cycle) {
        List<String> reversed = new ArrayList<>(cycle);
        java.util.Collections.reverse(reversed);
        return reversed;
    }

    /** 사이클을 두 바퀴로 펼쳐 노선을 만든다. 구간 행이 없으면 null(값을 지어내지 않음). */
    private static RaptorFinder.Route materializeCycle(String routeId, List<String> cycle,
                                                        List<RouteEdgeRow> rows) {
        Map<String, RouteEdgeRow> byDirection = new LinkedHashMap<>();
        for (RouteEdgeRow row : rows) {
            byDirection.putIfAbsent(row.fromNode() + "->" + row.toNode(), row);
        }
        int n = cycle.size();
        List<String> stops = new ArrayList<>();
        int[] travel = new int[n * 2];
        int[] waits = new int[n * 2 + 1];
        for (int lap = 0; lap < 2; lap++) {
            for (int i = 0; i < n; i++) {
                String from = cycle.get(i);
                String to = cycle.get((i + 1) % n);
                RouteEdgeRow row = byDirection.get(from + "->" + to);
                if (row == null) {
                    return null;
                }
                stops.add(from);
                int index = lap * n + i;
                travel[index] = row.travelSec();
                waits[index] = row.waitSec();
            }
        }
        stops.add(cycle.get(0));
        return new RaptorFinder.Route(routeId, TravelMode.SUBWAY, List.copyOf(stops), travel, waits);
    }

    /** 버스 노선 CSV(순번) → 순서 배열. 좌표 없는 정류장에서 체인을 끊고 조각별로 노선을 만든다. */
    public static List<RaptorFinder.Route> busRoutes(
            Map<String, List<BusEdgeBuilder.RouteStop>> routes) {
        List<RaptorFinder.Route> out = new ArrayList<>();
        for (Map.Entry<String, List<BusEdgeBuilder.RouteStop>> entry : routes.entrySet()) {
            List<BusEdgeBuilder.RouteStop> stops = new ArrayList<>(entry.getValue());
            stops.sort(Comparator.comparing(BusEdgeBuilder.RouteStop::seq,
                    Comparator.nullsLast(Integer::compareTo)));
            List<Segment> segments = new ArrayList<>();
            int part = 0;
            BusEdgeBuilder.RouteStop prev = null;
            for (BusEdgeBuilder.RouteStop stop : stops) {
                if (stop.lat() == null || stop.lng() == null) {
                    part = flush(entry.getKey(), part, segments, out);
                    prev = null;
                    continue;
                }
                if (prev != null) {
                    int sec = Math.max(1, (int) Math.round(BusEdgeBuilder.distanceM(prev, stop)
                            / BusEdgeBuilder.METERS_PER_SEC));
                    // 218(버스 대기 배선) 전까지 승차 대기 0.
                    segments.add(new Segment(prev.stopId(), stop.stopId(), sec, 0));
                }
                prev = stop;
            }
            flush(entry.getKey(), part, segments, out);
        }
        return out;
    }

    /** 도보·자전거 연결 — 기존 빌더 재사용. */
    public static List<RaptorFinder.Connection> connections(
            Map<String, BikeEdgeBuilder.Stop> stations,
            Map<String, BikeEdgeBuilder.Stop> rentals,
            Map<String, BikeEdgeBuilder.Stop> busStops) {
        List<RaptorFinder.Connection> connections = new ArrayList<>();
        for (Edge edge : WalkEdgeBuilder.build(stations, rentals, busStops)) {
            connections.add(new RaptorFinder.Connection(
                    edge.fromNode(), edge.toNode(), edge.travelSec(), TravelMode.WALK));
        }
        for (Edge edge : BikeRentalEdgeBuilder.build(rentals)) {
            connections.add(new RaptorFinder.Connection(
                    edge.fromNode(), edge.toNode(), edge.travelSec(), TravelMode.BIKE));
        }
        return connections;
    }

    private static int flush(String routeId, int part, List<Segment> segments,
                             List<RaptorFinder.Route> out) {
        if (segments.size() >= 1) {
            String id = part == 0 ? routeId : routeId + "#" + part;
            materialize(id, TravelMode.BUS, segments, out);
            part++;
        }
        segments.clear();
        return part;
    }

    /** 이어진 구간 목록 → 노선 하나. 승차 대기는 구간의 waitSec을 출발 정류장의 값으로 옮긴다. */
    private static void materialize(String routeId, TravelMode mode, List<Segment> segments,
                                    List<RaptorFinder.Route> out) {
        if (segments.size() < 1) {
            return;
        }
        List<String> stops = new ArrayList<>();
        stops.add(segments.get(0).from());
        int[] travel = new int[segments.size()];
        int[] waits = new int[segments.size() + 1];
        for (int i = 0; i < segments.size(); i++) {
            Segment segment = segments.get(i);
            stops.add(segment.to());
            travel[i] = segment.travelSec();
            waits[i] = segment.waitSec();
        }
        if (stops.size() < 2) {
            return;
        }
        out.add(new RaptorFinder.Route(routeId, mode, List.copyOf(stops), travel, waits));
    }

    /** 그룹을 from→to 인접으로 이어 순서 배열을 만든다. 진입 0인 시작점이 없으면 순환선으로 취급. */
    private static List<Segment> chain(List<Segment> group, String lineId) {
        Map<String, Segment> outgoing = new LinkedHashMap<>();
        Map<String, Integer> inDegree = new LinkedHashMap<>();
        for (Segment segment : group) {
            outgoing.putIfAbsent(segment.from(), segment);
            inDegree.putIfAbsent(segment.from(), 0);
            inDegree.merge(segment.to(), 1, Integer::sum);
        }
        String start = null;
        for (Map.Entry<String, Integer> entry : inDegree.entrySet()) {
            if (entry.getValue() == 0) {
                start = entry.getKey();
                break;
            }
        }
        if (start == null) {
            // 순환선: 임의 시작으로 사이클을 걷고 두 바퀴로 펼친다(한 바퀴 이내 순환 표현).
            start = group.get(0).from();
            List<Segment> cycle = walk(outgoing, start);
            List<Segment> doubled = new ArrayList<>(cycle);
            doubled.addAll(cycle);
            if (cycle.size() != inDegree.size()) {
                log.debug("지하철 순환선 절단? {} 사이클 {} / 정점 {}", lineId, cycle.size(), inDegree.size());
            }
            return doubled;
        }
        return walk(outgoing, start);
    }

    private static List<Segment> walk(Map<String, Segment> outgoing, String start) {
        List<Segment> segments = new ArrayList<>();
        java.util.Set<String> visited = new java.util.HashSet<>();
        String current = start;
        while (outgoing.containsKey(current)) {
            Segment segment = outgoing.get(current);
            if (!visited.add(current)) {
                break; // 사이클 보호
            }
            segments.add(segment);
            current = segment.to();
        }
        return segments;
    }

    /** 보류 링크를 기존 체인 끝/시작에 붙인다. 붙지 않으면 false. */
    private static boolean attach(List<List<Segment>> chains, RouteEdgeRow row) {
        for (List<Segment> chain : chains) {
            if (!chain.isEmpty() && chain.get(chain.size() - 1).to().equals(row.fromNode())) {
                chain.add(Segment.of(row));
                return true;
            }
            if (!chain.isEmpty() && chain.get(0).from().equals(row.toNode())) {
                chain.add(0, Segment.of(row));
                return true;
            }
        }
        return false;
    }

    private record Segment(String from, String to, int travelSec, int waitSec) {
        static Segment of(RouteEdgeRow row) {
            return new Segment(row.fromNode(), row.toNode(), row.travelSec(), row.waitSec());
        }
    }
}
