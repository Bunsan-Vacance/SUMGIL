package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.PriorityQueue;
import java.util.Set;

/**
 * 단일 그래프 1회 기반 K개 후보 탐색(Yen's K-shortest, S15P21A104-213 T2).
 *
 * <p>7개 하위 그래프 반복 탐색을 대체한다. 원본 그래프 1개에서 서로 다른 leg 서명의
 * 후보를 최대 K개까지 뽑는다. 환승 비용·판정은 {@link TransferRule}에 위임한다.
 * 순수 로직이며 DB·Redis에 접근하지 않는다.
 */
public final class KShortestPathFinder {

    private final ShortestPathFinder single;
    private final TransferRule transferRule;

    /**
     * @param transferRule 환승 비용 규칙. 탐색기 내부에서 공유한다
     */
    public KShortestPathFinder(TransferRule transferRule) {
        this.transferRule = transferRule;
        this.single = new ShortestPathFinder(transferRule);
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
        List<FoundPath> accepted = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        PriorityQueue<FoundPath> candidates = new PriorityQueue<>(
                Comparator.comparingLong(FoundPath::totalSec));

        try {
            FoundPath first = single.find(graph, originStationId, destStationId);
            candidates.add(first);
        } catch (RuntimeException e) {
            return List.of();
        }

        while (!candidates.isEmpty() && accepted.size() < k) {
            FoundPath best = candidates.poll();
            String signature = signatureOf(best);
            if (!seen.add(signature)) {
                continue;
            }
            accepted.add(best);
            if (accepted.size() >= k) {
                break;
            }
            for (FoundPath spur : spurCandidates(
                    graph, best, accepted, seen, originStationId, destStationId)) {
                candidates.add(spur);
            }
        }
        return List.copyOf(accepted);
    }

    /**
     * Yen's 분기: 경로의 각 정점을 spur 노드로 삼아, 지금까지 확정된 모든 경로와
     * 겹치는 엣지를 금지한 그래프에서 spur 경로를 찾고 앞부분과 이어붙인다.
     */
    private List<FoundPath> spurCandidates(RouteGraph graph, FoundPath base,
                                           List<FoundPath> accepted, Set<String> seen,
                                           String origin, String dest) {
        List<FoundPath> result = new ArrayList<>();
        List<Edge> baseEdges = base.edges();
        List<String> baseStations = base.stations();
        for (int i = 0; i < baseEdges.size(); i++) {
            String spurNode = baseStations.get(i);
            List<Edge> rootEdges = new ArrayList<>(baseEdges.subList(0, i));
            Set<EdgeKey> banned = new LinkedHashSet<>();
            // root 구간이 같은 확정 경로들의 i번째 엣지를 전부 금지한다.
            for (FoundPath other : accepted) {
                if (other.edges().size() <= i) {
                    continue;
                }
                boolean sameRoot = rootPrefix(other.edges(), rootEdges);
                if (sameRoot) {
                    Edge bannedEdge = other.edges().get(i);
                    banned.add(new EdgeKey(bannedEdge.fromNode(), bannedEdge.toNode(), bannedEdge.routeId()));
                }
            }
            RouteGraph restricted = restrictedGraph(graph, banned,
                    rootStations(rootEdges, origin), spurNode);
            FoundPath spur;
            try {
                spur = single.find(restricted, spurNode, dest);
            } catch (RuntimeException e) {
                continue;
            }
            FoundPath combined = combine(rootEdges, spur, origin);
            if (combined != null && !seen.contains(signatureOf(combined))) {
                result.add(combined);
            }
        }
        return result;
    }

    /** root 구간이 확정 경로의 앞부분과 같은지 비교한다 (엣지 단위). */
    private static boolean rootPrefix(List<Edge> edges, List<Edge> rootEdges) {
        if (edges.size() < rootEdges.size()) {
            return false;
        }
        for (int i = 0; i < rootEdges.size(); i++) {
            Edge a = edges.get(i);
            Edge b = rootEdges.get(i);
            if (!a.fromNode().equals(b.fromNode()) || !a.toNode().equals(b.toNode())
                    || !a.routeId().equals(b.routeId())) {
                return false;
            }
        }
        return true;
    }

    /** root 구간 정점 집합(출발역 포함, spur 노드 제외) — 루프 방지용 금지 집합. */
    private Set<String> rootStations(List<Edge> rootEdges, String origin) {
        Set<String> stations = new LinkedHashSet<>();
        stations.add(origin);
        for (Edge edge : rootEdges) {
            stations.add(edge.toNode());
        }
        return stations;
    }

    /** 금지 엣지·root 정점을 제외한 그래프를 만든다. spur 노드는 유지한다. */
    private RouteGraph restrictedGraph(RouteGraph graph, Set<EdgeKey> banned,
                                       Set<String> rootStations, String spurNode) {
        Set<String> nodes = new LinkedHashSet<>(graph.nodes());
        java.util.Map<String, List<Edge>> adjacency = new java.util.LinkedHashMap<>();
        java.util.Map<String, Set<String>> lines = new java.util.LinkedHashMap<>();
        for (Edge edge : graph.edges()) {
            if (banned.contains(new EdgeKey(edge.fromNode(), edge.toNode(), edge.routeId()))) {
                continue;
            }
            adjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>()).add(edge);
            lines.computeIfAbsent(edge.fromNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
            lines.computeIfAbsent(edge.toNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
        }
        // root 정점 진입 금지: spur 탐색이 이미 지난 정점으로 루프하지 않게 한다.
        // spur 노드 자체는 탐색 시작점이라 남긴다.
        for (String station : rootStations) {
            if (station.equals(spurNode)) {
                continue;
            }
            adjacency.remove(station);
            nodes.remove(station);
        }
        return RouteGraph.of(nodes, adjacency, lines);
    }

    /** root 엣지 + spur 경로를 이어붙인다. 연속성 깨지면 null. */
    private FoundPath combine(List<Edge> rootEdges, FoundPath spur, String origin) {
        List<Edge> edges = new ArrayList<>(rootEdges);
        edges.addAll(spur.edges());
        List<String> stations = new ArrayList<>();
        stations.add(origin);
        for (Edge edge : edges) {
            stations.add(edge.toNode());
        }
        // 연속성: root 끝과 spur 시작이 이어져야 한다.
        if (!spur.stations().isEmpty()) {
            String rootEnd = rootEdges.isEmpty() ? origin : rootEdges.get(rootEdges.size() - 1).toNode();
            if (!spur.stations().get(0).equals(rootEnd)) {
                return null;
            }
        }
        // 소요 = root 구간 순수 소요 + 첫 승차 대기(190) + spur 전체(내부 환승 포함)
        // + root끝→spur시작 경계 환승(노선유지 판정, 232).
        // root 비어 있으면 spur.totalSec에 첫 승차 대기가 이미 포함돼 있다.
        long totalSec = rootEdges.stream().mapToLong(e -> (long) e.travelSec()).sum()
                + spur.totalSec();
        if (!rootEdges.isEmpty()) {
            totalSec += rootEdges.get(0).waitSec();
        }
        String junctionKept = null;
        for (Edge edge : rootEdges) {
            junctionKept = TransferRule.keptTransitLine(
                    junctionKept, edge.mode(), edge.routeId());
        }
        if (!rootEdges.isEmpty() && !spur.edges().isEmpty()) {
            Edge last = rootEdges.get(rootEdges.size() - 1);
            Edge first = spur.edges().get(0);
            TransferRule.TransferDecision junction = TransferRule.decide(
                    junctionKept, last.mode(), last.routeId(), first.mode(), first.routeId());
            if (junction.transfer()) {
                totalSec += transferRule.costWithStation(
                        0, first.fromNode(), junction.costLine(), first.routeId());
            }
        }
        int transfers = 0;
        String kept = null;
        com.ssafy.s15p21a104.domain.route.entity.TravelMode prevMode = null;
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
        // spur 탐색에서 금지한 root 정점을 stations에서 빼면 edges/stations 개수가
        // 어긋날 수 있어 FoundPath 검증을 통과 못 하면 버린다.
        try {
            return new FoundPath(List.copyOf(stations), List.copyOf(edges), totalSec, transfers);
        } catch (IllegalArgumentException e) {
            return null;
        }
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

    private record EdgeKey(String from, String to, String routeId) {
    }
}
