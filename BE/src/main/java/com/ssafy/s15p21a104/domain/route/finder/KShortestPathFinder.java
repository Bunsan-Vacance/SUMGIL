package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.PriorityQueue;
import java.util.Set;

/**
 * 단일 그래프 1회 K개 후보 탐색 — 정점·상태당 K 라벨 확정(S15P21A104-215).
 *
 * <p>Yen의 spur 재탐색(경로 길이 × K회)을 없앤다. 다익스트라를 한 번 돌리면서
 * (역, 도착 노선, 유지 노선 집합) 상태마다 최대 K개 라벨 확정을 허용하고, 도착지에서
 * 확정되는 순서(비용 오름차순)대로 서로 다른 후보를 모은다.
 *
 * <p>되돌아감은 상태별 64비트 방문 플래그로 막는다 — 비트가 꺼져 있으면 확실히 처음
 * 지나는 정점이고, 켜져 있으면(해시 충돌 가능) 부모 사슬을 훑어 정확히 확인한다.
 * 순수 로직이며 DB·Redis에 접근하지 않는다.
 */
public final class KShortestPathFinder {

    private final TransferRule transferRule;
    private final BusRouteIndex busRouteIndex;

    /**
     * @param transferRule 환승 비용 규칙. 탐색기 내부에서 공유한다
     */
    public KShortestPathFinder(TransferRule transferRule) {
        this(transferRule, null);
    }

    /**
     * @param transferRule 환승 비용 규칙. 탐색기 내부에서 공유한다
     * @param busRouteIndex 정규 BUS 구간 운행 노선 인덱스(234). null이면 routeId 폴백
     */
    public KShortestPathFinder(TransferRule transferRule, BusRouteIndex busRouteIndex) {
        this.transferRule = transferRule;
        this.busRouteIndex = busRouteIndex;
    }

    /**
     * 출발역에서 도착역까지 서로 다른 후보를 최대 K개 찾는다.
     *
     * @param graph 인메모리 유향 그래프
     * @param originStationId 출발역 ID
     * @param destStationId 도착역 ID
     * @param k 최대 후보 수. 1 이하면 빈 목록
     * @return 소요시간 오름차순 후보. 경로 없으면 빈 목록
     */
    public List<FoundPath> findK(RouteGraph graph, String originStationId, String destStationId, int k) {
        Objects.requireNonNull(graph, "graph");
        if (k <= 0) {
            return List.of();
        }
        if (Objects.equals(originStationId, destStationId)) {
            return List.of();
        }
        if (!graph.containsNode(originStationId) || !graph.containsNode(destStationId)) {
            return List.of();
        }

        Map<String, Map<StateKey, List<Label>>> labelsByNode = new HashMap<>();
        PriorityQueue<Label> queue = new PriorityQueue<>(Comparator.comparingLong(Label::cost));
        long originBit = bitOf(originStationId);

        // 첫 탑승: 환승 아님, 첫 승차 대기 1회(190).
        for (Edge edge : graph.outgoingEdges(originStationId)) {
            if (originStationId.equals(edge.toNode())) {
                continue;
            }
            long cost = transferRule.costWithStation(
                    edge.travelSec(), originStationId, null, edge.routeId(), null, edge.mode())
                    + edge.waitSec();
            Set<String> options = BusRouteIndex.optionsFor(edge, busRouteIndex);
            Set<String> kept = TransferRule.keptTransitLines(Set.of(), edge.mode(), options);
            Label label = new Label(cost, null, edge, edge.toNode(), edge.mode(), kept, options,
                    originBit | bitOf(edge.toNode()));
            if (addLabel(labelsByNode, label, k)) {
                queue.add(label);
            }
        }

        List<FoundPath> results = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        while (!queue.isEmpty() && results.size() < k) {
            Label label = queue.poll();
            if (!isCurrent(labelsByNode, label)) {
                continue;
            }
            if (label.node().equals(destStationId)) {
                FoundPath path = buildPath(label, originStationId);
                if (seen.add(signatureOf(path))) {
                    results.add(path);
                }
                continue;
            }
            for (Edge edge : graph.outgoingEdges(label.node())) {
                long targetBit = bitOf(edge.toNode());
                if (isVisited(label, edge.toNode(), targetBit)) {
                    continue;
                }
                Set<String> options = BusRouteIndex.optionsFor(edge, busRouteIndex);
                TransferRule.TransferDecision decision = TransferRule.decideLines(
                        label.keptLine(), label.arrivalMode(), label.arrivedOptions(),
                        edge.mode(), options);
                long nextCost = label.cost() + edge.travelSec();
                if (decision.transfer()) {
                    nextCost += transferRule.transferCost(label.node(), label.keptLine(), options);
                } else if (label.arrivedOptions().size() == 1 && options.size() == 1) {
                    // 집합 판정이 닿지 않는 기존 직접 경계(대중교통↔BIKE)는 문자열 규칙으로
                    // 그대로 본다 — 단일 노선 그래프에서 232와 바이트 동일.
                    String nextLine = options.iterator().next();
                    TransferRule.TransferDecision legacy = TransferRule.decide(
                            singleOrNull(label.keptLine()), label.arrivalMode(),
                            label.arrivedOptions().iterator().next(), edge.mode(), nextLine);
                    if (legacy.transfer()) {
                        nextCost += transferRule.costWithStation(
                                0, label.node(), legacy.costLine(), nextLine);
                    }
                }
                Set<String> nextKept = TransferRule.keptTransitLines(
                        label.keptLine(), edge.mode(), options);
                Label child = new Label(nextCost, label, edge, edge.toNode(), edge.mode(),
                        nextKept, options, label.seenBits() | targetBit);
                if (addLabel(labelsByNode, child, k)) {
                    queue.add(child);
                }
            }
        }
        return List.copyOf(results);
    }

    /**
     * (역, 상태)당 최대 K개 라벨만 유지한다. 자리가 없고 새 비용이 최악보다 나쁘면 버린다.
     */
    private static boolean addLabel(Map<String, Map<StateKey, List<Label>>> labelsByNode,
                                    Label label, int k) {
        List<Label> list = labelsByNode
                .computeIfAbsent(label.node(), node -> new HashMap<>())
                .computeIfAbsent(stateKeyOf(label), key -> new ArrayList<>(k));
        if (list.size() < k) {
            list.add(label);
            return true;
        }
        int worst = 0;
        for (int i = 1; i < list.size(); i++) {
            if (list.get(i).cost() > list.get(worst).cost()) {
                worst = i;
            }
        }
        if (label.cost() < list.get(worst).cost()) {
            list.set(worst, label);
            return true;
        }
        return false;
    }

    /** 큐에서 꺼낸 라벨이 아직 유지 중인지(더 나은 라벨에 밀려나지 않았는지) 확인한다. */
    private static boolean isCurrent(Map<String, Map<StateKey, List<Label>>> labelsByNode, Label label) {
        Map<StateKey, List<Label>> byKey = labelsByNode.get(label.node());
        if (byKey == null) {
            return false;
        }
        List<Label> list = byKey.get(stateKeyOf(label));
        return list != null && list.contains(label);
    }

    private static StateKey stateKeyOf(Label label) {
        return new StateKey(label.edge().routeId(), label.keptLine());
    }

    /**
     * 이 라벨의 경로가 이미 지난 정점인지 확인한다. 비트가 꺼져 있으면 확실히 안 지났고,
     * 켜져 있으면 해시 충돌일 수 있으니 부모 사슬을 훑어 정확히 확인한다.
     */
    private static boolean isVisited(Label label, String station, long bit) {
        if ((label.seenBits() & bit) == 0L) {
            return false;
        }
        Label current = label;
        while (current != null) {
            if (current.node().equals(station) || current.edge().fromNode().equals(station)) {
                return true;
            }
            current = current.parent();
        }
        return false;
    }

    private static long bitOf(String station) {
        return 1L << (station.hashCode() & 63);
    }

    private FoundPath buildPath(Label arrival, String originStationId) {
        List<Edge> edges = new ArrayList<>();
        Label current = arrival;
        while (current != null) {
            edges.add(0, current.edge());
            current = current.parent();
        }
        List<String> stations = new ArrayList<>();
        stations.add(originStationId);
        for (Edge edge : edges) {
            stations.add(edge.toNode());
        }

        int transfers = 0;
        Set<String> kept = Set.of();
        TravelMode prevMode = null;
        Set<String> prevOptions = Set.of();
        for (Edge edge : edges) {
            // 환승 집계도 TransferRule 1곳으로 통일한다(232·234).
            Set<String> options = BusRouteIndex.optionsFor(edge, busRouteIndex);
            if (prevMode != null) {
                boolean transfer = TransferRule.decideLines(
                        kept, prevMode, prevOptions, edge.mode(), options).transfer();
                if (!transfer && prevOptions.size() == 1 && options.size() == 1) {
                    transfer = TransferRule.decide(
                            singleOrNull(kept), prevMode, prevOptions.iterator().next(),
                            edge.mode(), options.iterator().next()).transfer();
                }
                if (transfer) {
                    transfers++;
                }
            }
            prevOptions = options;
            kept = TransferRule.keptTransitLines(kept, edge.mode(), options);
            prevMode = edge.mode();
        }
        return new FoundPath(List.copyOf(stations), List.copyOf(edges), arrival.cost(), transfers);
    }

    /** 단일 원소 집합이면 그 원소, 아니면 null — 기존 문자열 규칙 폴백용. */
    private static String singleOrNull(Set<String> lines) {
        if (lines == null || lines.size() != 1) {
            return null;
        }
        return lines.iterator().next();
    }

    /** leg 서명: (수단·출발·도착·노선) 순서. 같으면 같은 경로로 본다. */
    private static String signatureOf(FoundPath path) {
        StringBuilder signature = new StringBuilder();
        for (Edge edge : path.edges()) {
            signature.append(edge.mode()).append(':')
                    .append(edge.fromNode()).append("->").append(edge.toNode()).append(':')
                    .append(edge.routeId()).append('|');
        }
        return signature.toString();
    }

    /** 탐색 상태 키 — (도착 노선, 유지 노선 집합). */
    private record StateKey(String line, Set<String> keptLine) {
    }

    /**
     * 확정 라벨 1개. 부모 사슬(되돌아감 확인·경로 복원)과 방문 비트(64비트 필터)를 든다.
     */
    private record Label(long cost, Label parent, Edge edge, String node, TravelMode arrivalMode,
                         Set<String> keptLine, Set<String> arrivedOptions, long seenBits) {
    }
}
