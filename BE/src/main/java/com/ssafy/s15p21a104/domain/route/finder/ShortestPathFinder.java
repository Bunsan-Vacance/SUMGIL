package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.PriorityQueue;

/**
 * 인메모리 유향 그래프 최단 경로 1개(K=1) 탐색(Dijkstra, 우선순위 큐).
 *
 * <p>순수 로직이며 DB·Redis에 접근하지 않는다. 그래프는 94 산출물({@link RouteGraph})을
 * 그대로 쓰고, 환승 비용 값·판정은 96 산출물({@link TransferRule})에 위임한다(중복 정의 없음).
 *
 * <p>환승 상수가 현재 노선에 따라 달라지므로 탐색 상태는 (역, 현재 노선) 쌍으로 둔다.
 * 출발 직후 첫 엣지는 환승이 아니다. 가중치가 음이 아니므로 반환 경로는 재방문 없는 단순 경로이다.
 */
public final class ShortestPathFinder {

    private final TransferRule transferRule;

    /**
     * @param transferRule 환승 비용 규칙(96). 상수 값·판정 함수의 정본
     */
    public ShortestPathFinder(TransferRule transferRule) {
        this.transferRule = Objects.requireNonNull(transferRule, "transferRule");
    }

    /**
     * 출발역에서 도착역까지 소요시간 최단 경로 1개를 찾는다.
     *
     * @param graph 인메모리 유향 그래프(94 산출물)
     * @param originStationId 출발역 ID
     * @param destStationId 도착역 ID
     * @return 최단 경로(정점 순서·총 소요·환승 횟수·구간 노선)
     * @throws DomainException 출발=도착({@code SAME_ORIGIN_DEST})·미등록 역({@code STATION_NOT_FOUND})·연결 불가({@code ROUTE_NOT_FOUND})
     */
    public FoundPath find(RouteGraph graph, String originStationId, String destStationId) {
        Objects.requireNonNull(graph, "graph");
        if (Objects.equals(originStationId, destStationId)) {
            throw new DomainException(ErrorType.SAME_ORIGIN_DEST);
        }
        if (!graph.containsNode(originStationId) || !graph.containsNode(destStationId)) {
            throw new DomainException(ErrorType.STATION_NOT_FOUND);
        }

        // dist: 역 → (도착 시 노선 → 최소 비용). prev: 역 → (도착 시 노선 → 이전 상태).
        Map<String, Map<String, Long>> dist = new HashMap<>();
        Map<String, Map<String, Previous>> prev = new HashMap<>();
        PriorityQueue<State> queue = new PriorityQueue<>(Comparator.comparingLong(State::cost));

        // 출발 직후 첫 엣지는 환승 아님(현재 노선 없음).
        for (Edge edge : graph.outgoingEdges(originStationId)) {
            long cost = transferRule.costWithStation(
                    edge.travelSec(), originStationId, null, edge.routeId());
            if (cost < costOf(dist, edge.toNode(), edge.routeId())) {
                setCost(dist, edge.toNode(), edge.routeId(), cost);
                prev.computeIfAbsent(edge.toNode(), key -> new HashMap<>())
                        .put(edge.routeId(), new Previous(originStationId, null, edge));
                queue.add(new State(cost, edge.toNode(), edge.routeId()));
            }
        }

        while (!queue.isEmpty()) {
            State current = queue.poll();
            if (current.cost() != costOf(dist, current.node(), current.line())) {
                continue;
            }
            if (current.node().equals(destStationId)) {
                return buildPath(prev, originStationId, current);
            }
            for (Edge edge : graph.outgoingEdges(current.node())) {
                // 환승은 현재 서 있는 역에서 일어난다. 실측 없으면 상수로 폴백한다.
                long nextCost = current.cost() + transferRule.costWithStation(
                        edge.travelSec(), current.node(), current.line(), edge.routeId());
                if (nextCost < costOf(dist, edge.toNode(), edge.routeId())) {
                    setCost(dist, edge.toNode(), edge.routeId(), nextCost);
                    prev.computeIfAbsent(edge.toNode(), key -> new HashMap<>())
                            .put(edge.routeId(), new Previous(current.node(), current.line(), edge));
                    queue.add(new State(nextCost, edge.toNode(), edge.routeId()));
                }
            }
        }

        throw new DomainException(ErrorType.ROUTE_NOT_FOUND);
    }

    private FoundPath buildPath(Map<String, Map<String, Previous>> prev,
                                String originStationId, State arrival) {
        List<Edge> edges = new ArrayList<>();
        String node = arrival.node();
        String line = arrival.line();
        while (true) {
            Previous previous = prevOf(prev, node, line);
            if (previous == null) {
                throw new IllegalStateException("경로 역추적 실패: " + node + "/" + line);
            }
            edges.add(0, previous.edge());
            if (previous.fromNode().equals(originStationId)) {
                break;
            }
            node = previous.fromNode();
            line = previous.fromLine();
        }

        List<String> stations = new ArrayList<>();
        stations.add(originStationId);
        for (Edge edge : edges) {
            stations.add(edge.toNode());
        }

        int transfers = 0;
        for (int i = 1; i < edges.size(); i++) {
            if (!edges.get(i).routeId().equals(edges.get(i - 1).routeId())) {
                transfers++;
            }
        }

        return new FoundPath(List.copyOf(stations), List.copyOf(edges), arrival.cost(), transfers);
    }

    private Previous prevOf(Map<String, Map<String, Previous>> prev, String node, String line) {
        Map<String, Previous> byLine = prev.get(node);
        return byLine == null ? null : byLine.get(line);
    }

    private long costOf(Map<String, Map<String, Long>> dist, String node, String line) {
        Map<String, Long> byLine = dist.get(node);
        if (byLine == null) {
            return Long.MAX_VALUE;
        }
        return byLine.getOrDefault(line, Long.MAX_VALUE);
    }

    private void setCost(Map<String, Map<String, Long>> dist, String node, String line, long cost) {
        dist.computeIfAbsent(node, key -> new HashMap<>()).put(line, cost);
    }

    private record State(long cost, String node, String line) {
    }

    private record Previous(String fromNode, String fromLine, Edge edge) {
    }
}
