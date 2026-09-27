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
            // 체인 연결: 방향 그룹마다 **모든** 체인을 조립한다(진입 0 시작점들 + 남은 순환).
            // 행 순서와 무관하게 결정적이어야 한다 — 예전 구현은 시작점 하나와 나가는 구간
            // 하나(putIfAbsent)만 골라, 지선·분기가 섞인 2호선에서 본선 체인이 통째로 빠질 수
            // 있었다(prod 슬롯별 flakiness: Parallel Seq Scan 행 순서 + 슬롯 캐시 고정).
            List<List<Segment>> ordered = new ArrayList<>();
            for (List<Segment> group : chains.values()) {
                ordered.addAll(chains(group));
            }
            // 규칙 보류 링크(반전 3개)는 체인 끝/시작에 붙인다. 못 붙이면 버린다(값을 지어내지 않음).
            for (RouteEdgeRow row : unresolved) {
                if (!attach(ordered, row)) {
                    log.debug("지하철 미해결 링크 버림: {} {}->{}", lineId, row.fromNode(), row.toNode());
                }
            }
            // 환승역이 다른 노선의 작은 역사코드를 물려받은 노선(수인분당·8호선 가락시장/남위례 등)은
            // 역번호가 오르내려 같은 물리 방향이 여러 그룹으로 흩어지고 체인이 조각난다. 조각마다
            // 재승차 대기가 붙으므로 이어지는 조각이 하나뿐이면 잇는다(267).
            stitch(ordered);
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

    /**
     * 금지 구간({"from->to"})을 제거한 노선 목록 — K 후보를 얻기 위한 반복 스캔용(217 K 전략).
     * 구간이 빠지면 노선이 조각나므로 조각들을 각각 노선으로 만든다(값을 지어내지 않음).
     */
    public static List<RaptorFinder.Route> withoutSegments(
            List<RaptorFinder.Route> routes, java.util.Set<String> bannedSegments) {
        if (routes == null || routes.isEmpty() || bannedSegments == null
                || bannedSegments.isEmpty()) {
            return routes == null ? List.of() : routes;
        }
        List<RaptorFinder.Route> out = new ArrayList<>();
        for (RaptorFinder.Route route : routes) {
            List<String> stops = route.stops();
            int start = 0;
            for (int i = 0; i + 1 < stops.size(); i++) {
                if (!bannedSegments.contains(stops.get(i) + "->" + stops.get(i + 1))) {
                    continue;
                }
                if (i > start) {
                    splitInto(route, start, i + 1, out);
                }
                start = i + 1;
            }
            if (stops.size() - start >= 2) {
                splitInto(route, start, stops.size(), out);
            }
        }
        return out;
    }

    /** 원 노선의 [fromIdx, toIdx) 정류장 조각을 노선으로 만든다. */
    private static void splitInto(RaptorFinder.Route route, int fromIdx, int toIdx,
                                  List<RaptorFinder.Route> out) {
        List<String> subStops = new ArrayList<>(route.stops().subList(fromIdx, toIdx));
        int[] subTravel = java.util.Arrays.copyOfRange(route.travelSec(), fromIdx, toIdx - 1);
        int[] subWait = java.util.Arrays.copyOfRange(route.boardWaitSec(), fromIdx, toIdx);
        out.add(new RaptorFinder.Route(route.routeId(), route.mode(), List.copyOf(subStops),
                subTravel, subWait));
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

    /**
     * 방향 그룹의 구간들을 체인들로 조립한다 — 진입 0 시작점마다 하나씩, 남은 순환은 각각.
     * 입력 행 순서에 의존하지 않는다(TreeMap·정렬된 시작점). 순환은 두 바퀴로 펼친다.
     */
    private static List<List<Segment>> chains(List<Segment> group) {
        Map<String, List<Segment>> outgoing = new java.util.TreeMap<>();
        Map<String, Integer> inDegree = new java.util.TreeMap<>();
        for (Segment segment : group) {
            outgoing.computeIfAbsent(segment.from(), key -> new ArrayList<>()).add(segment);
            inDegree.merge(segment.to(), 1, Integer::sum);
            inDegree.putIfAbsent(segment.from(), 0);
        }
        for (List<Segment> candidates : outgoing.values()) {
            candidates.sort(Comparator.comparing(Segment::to));
        }
        java.util.Set<Segment> used = new java.util.HashSet<>();
        List<List<Segment>> chains = new ArrayList<>();
        for (Map.Entry<String, Integer> entry : inDegree.entrySet()) {
            if (entry.getValue() != 0) {
                continue;
            }
            List<Segment> chain = walkFrom(entry.getKey(), outgoing, used);
            if (!chain.isEmpty()) {
                chains.add(chain);
            }
        }
        // 남은 구간(순환 등) — 남은 정점 중 사전순 최소에서 걷는다. 시작으로 되돌아오면 순환.
        for (String start : outgoing.keySet()) {
            List<Segment> cycle = walkFrom(start, outgoing, used);
            if (cycle.isEmpty()) {
                continue;
            }
            boolean closed = cycle.get(cycle.size() - 1).to().equals(start);
            if (closed) {
                List<Segment> doubled = new ArrayList<>(cycle);
                doubled.addAll(cycle);
                chains.add(doubled);
            } else {
                chains.add(cycle);
            }
        }
        return chains;
    }

    /** 사용하지 않은 구간을 따라가며 체인 하나를 소비한다. 이미 지난 정점에서 멈춘다. */
    private static List<Segment> walkFrom(String start, Map<String, List<Segment>> outgoing,
                                          java.util.Set<Segment> used) {
        List<Segment> segments = new ArrayList<>();
        java.util.Set<String> visited = new java.util.HashSet<>();
        String current = start;
        while (visited.add(current)) {
            List<Segment> candidates = outgoing.get(current);
            Segment next = null;
            if (candidates != null) {
                for (Segment candidate : candidates) {
                    if (!used.contains(candidate)) {
                        next = candidate;
                        break;
                    }
                }
            }
            if (next == null) {
                break;
            }
            used.add(next);
            segments.add(next);
            current = next.to();
        }
        return segments;
    }

    /**
     * 조각 체인을 잇는다 — 더 이을 게 없을 때까지 반복. 이미 온전한 체인(종점 도달·분기 모호)은
     * 후보가 없거나 여럿이라 그대로 남는다.
     */
    private static void stitch(List<List<Segment>> chains) {
        boolean changed = true;
        while (changed) {
            changed = false;
            for (List<Segment> chain : chains) {
                List<Segment> next = uniqueContinuation(chain, chains);
                if (next != null) {
                    chain.addAll(next);
                    chains.removeIf(candidate -> candidate == next);
                    changed = true;
                    break;
                }
            }
        }
    }

    /**
     * 체인 끝 정점에서 시작하는 다른 체인 중, 직전 정점으로 되돌아가지 않고 끝 정점 외에 겹치는
     * 정점이 없는 것이 정확히 하나면 그 체인. 없거나 여럿(분기)이면 null.
     */
    private static List<Segment> uniqueContinuation(List<Segment> chain, List<List<Segment>> chains) {
        if (chain.isEmpty()) {
            return null;
        }
        Segment last = chain.get(chain.size() - 1);
        java.util.Set<String> visited = new java.util.HashSet<>();
        for (Segment segment : chain) {
            visited.add(segment.from());
            visited.add(segment.to());
        }
        List<Segment> found = null;
        for (List<Segment> candidate : chains) {
            if (candidate == chain || candidate.isEmpty()) {
                continue;
            }
            Segment first = candidate.get(0);
            if (!first.from().equals(last.to()) || first.to().equals(last.from())) {
                continue;
            }
            if (candidate.stream().anyMatch(segment -> visited.contains(segment.to()))) {
                continue;
            }
            if (found != null) {
                return null;
            }
            found = candidate;
        }
        return found;
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
