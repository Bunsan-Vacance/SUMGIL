package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
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

        // dist: 역 → ((도착 노선, 유지 노선) → 최소 비용). prev도 같은 키.
        // 유지 노선(keptLine)을 키에 넣는다(232) — 같은 역·같은 도착 노선이라도
        // 직전 대중교통이 다르면 이후 환승 비용이 달라진다.
        Map<String, Map<StateKey, Long>> dist = new HashMap<>();
        Map<String, Map<StateKey, Previous>> prev = new HashMap<>();
        PriorityQueue<State> queue = new PriorityQueue<>(Comparator.comparingLong(State::cost));

        // 출발 직후 첫 엣지는 환승 아님(현재 노선 없음).
        // 첫 승차 대기(waitSec)를 1회 부과한다(S15P21A104-190) — 탑승 전 대기다.
        for (Edge edge : graph.outgoingEdges(originStationId)) {
            long cost = transferRule.costWithStation(
                    edge.travelSec(), originStationId, null, edge.routeId(), null, edge.mode())
                    + edge.waitSec();
            String kept = TransferRule.keptTransitLine(null, edge.mode(), edge.routeId());
            StateKey key = new StateKey(edge.routeId(), kept);
            if (cost < costOf(dist, edge.toNode(), key)) {
                setCost(dist, edge.toNode(), key, cost);
                prev.computeIfAbsent(edge.toNode(), k -> new HashMap<>())
                        .put(key, new Previous(originStationId, null, null, null, edge));
                queue.add(new State(cost, edge.toNode(), edge.routeId(), edge.mode(), kept));
            }
        }

        while (!queue.isEmpty()) {
            State current = queue.poll();
            StateKey currentKey = new StateKey(current.line(), current.keptLine());
            if (current.cost() != costOf(dist, current.node(), currentKey)) {
                continue;
            }
            if (current.node().equals(destStationId)) {
                return buildPath(prev, originStationId, current);
            }
            for (Edge edge : graph.outgoingEdges(current.node())) {
                // 환승 판정은 TransferRule 1곳으로 통일한다(232).
                // WALK를 지나도 유지된 대중교통 노선으로 비교한다.
                TransferRule.TransferDecision decision = TransferRule.decide(
                        current.keptLine(), current.arrivalMode(), current.line(),
                        edge.mode(), edge.routeId());
                long nextCost = current.cost() + edge.travelSec();
                if (decision.transfer()) {
                    nextCost += transferRule.costWithStation(
                            0, current.node(), decision.costLine(), edge.routeId());
                }
                String nextKept = TransferRule.keptTransitLine(
                        current.keptLine(), edge.mode(), edge.routeId());
                StateKey nextKey = new StateKey(edge.routeId(), nextKept);
                if (nextCost < costOf(dist, edge.toNode(), nextKey)) {
                    setCost(dist, edge.toNode(), nextKey, nextCost);
                    prev.computeIfAbsent(edge.toNode(), k -> new HashMap<>())
                            .put(nextKey, new Previous(current.node(), current.line(),
                                    current.arrivalMode(), current.keptLine(), edge));
                    queue.add(new State(nextCost, edge.toNode(), edge.routeId(), edge.mode(), nextKept));
                }
            }
        }

        throw new DomainException(ErrorType.ROUTE_NOT_FOUND);
    }

    private FoundPath buildPath(Map<String, Map<StateKey, Previous>> prev,
                                String originStationId, State arrival) {
        List<Edge> edges = new ArrayList<>();
        String node = arrival.node();
        StateKey key = new StateKey(arrival.line(), arrival.keptLine());
        while (true) {
            Previous previous = prevOf(prev, node, key);
            if (previous == null) {
                throw new IllegalStateException("경로 역추적 실패: " + node + "/" + key);
            }
            edges.add(0, previous.edge());
            if (previous.fromNode().equals(originStationId)) {
                break;
            }
            node = previous.fromNode();
            key = new StateKey(previous.fromLine(), previous.fromKeptLine());
        }

        List<String> stations = new ArrayList<>();
        stations.add(originStationId);
        for (Edge edge : edges) {
            stations.add(edge.toNode());
        }

        int transfers = 0;
        String kept = null;
        TravelMode prevMode = null;
        String prevLine = null;
        for (Edge edge : edges) {
            // 환승 집계도 TransferRule 1곳으로 통일한다(232).
            if (prevMode != null) {
                TransferRule.TransferDecision decision = TransferRule.decide(
                        kept, prevMode, prevLine, edge.mode(), edge.routeId());
                if (decision.transfer()) {
                    transfers++;
                }
            }
            kept = TransferRule.keptTransitLine(kept, edge.mode(), edge.routeId());
            prevMode = edge.mode();
            prevLine = edge.routeId();
        }

        return new FoundPath(List.copyOf(stations), List.copyOf(edges), arrival.cost(), transfers);
    }

    private Previous prevOf(Map<String, Map<StateKey, Previous>> prev, String node, StateKey key) {
        Map<StateKey, Previous> byKey = prev.get(node);
        return byKey == null ? null : byKey.get(key);
    }

    private long costOf(Map<String, Map<StateKey, Long>> dist, String node, StateKey key) {
        Map<StateKey, Long> byKey = dist.get(node);
        if (byKey == null) {
            return Long.MAX_VALUE;
        }
        return byKey.getOrDefault(key, Long.MAX_VALUE);
    }

    private void setCost(Map<String, Map<StateKey, Long>> dist, String node, StateKey key, long cost) {
        dist.computeIfAbsent(node, k -> new HashMap<>()).put(key, cost);
    }

    private record StateKey(String line, String keptLine) {
    }

    private record State(long cost, String node, String line, TravelMode arrivalMode, String keptLine) {
    }

    private record Previous(String fromNode, String fromLine, TravelMode fromMode,
                              String fromKeptLine, Edge edge) {
    }
}
