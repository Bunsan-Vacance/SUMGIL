package com.ssafy.s15p21a104.domain.route.graph;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * 지하철 구간(SUBWAY)의 불변 인메모리 유향 그래프.
 *
 * <p>정점 = 역 ID 하나. 같은 역이 여러 노선에 걸쳐도 정점은 하나이며, 노선별 정점을 두지 않는다.
 * 엣지 = {@link Edge} 1개가 행 1개에 대응한다. 단방향 행만 있으면 역방향 엣지를 만들지 않는다.
 * 환승 노드·환승 엣지를 포함하지 않는다(환승은 별도 티켓에서 상수 비용으로 처리).
 *
 * <p>각 정점(역)의 소속 노선 목록은 그 역을 출발/도착으로 하는 엣지들의 {@code routeId} 집합에서
 * 파생된 값이다. {@code station} 엔티티에는 노선 컬럼이 없기 때문에 엣지가 유일한 출처이다.
 *
 * <p>생성은 {@link #of}로만 하며 내부 컬렉션을 모두 깊은 불변 뷰로 감싼다.
 * 따라서 로드 후에는 정점·엣지·소속 노선을 변경하거나 추가할 수 없다.
 */
public final class RouteGraph {

    /** 정점(역 ID) 목록. */
    private final Set<String> nodes;

    /** 인접 리스트. key = 출발 역 ID, value = 해당 역에서 나가는 유향 엣지 목록(순서 유지). */
    private final Map<String, List<Edge>> adjacency;

    /** 정점별 소속 노선. key = 역 ID, value = 그 역을 잇는 엣지에서 파생된 노선 ID 집합. */
    private final Map<String, Set<String>> stationLines;

    private RouteGraph(Set<String> nodes,
                       Map<String, List<Edge>> adjacency,
                       Map<String, Set<String>> stationLines) {
        this.nodes = nodes;
        this.adjacency = adjacency;
        this.stationLines = stationLines;
    }

    /**
     * 조립 결과를 불변 그래프로 감싼다.
     *
     * <p>호출 직후부터 그래프는 불변이다. 입력 컬렉션을 깊은 복사한 뒤
     * 불변 뷰로 교체하고 복사본만 내부에 보관한다.
     *
     * @param nodes 전체 정점(역 ID)
     * @param adjacency 출발 역 ID별 유향 엣지 목록
     * @param stationLines 역 ID별 소속 노선 집합(엣지 routeId에서 파생)
     * @return 불변 그래프
     */
    public static RouteGraph of(Set<String> nodes,
                                Map<String, List<Edge>> adjacency,
                                Map<String, Set<String>> stationLines) {
        Set<String> copiedNodes = Collections.unmodifiableSet(new LinkedHashSet<>(nodes));

        Map<String, List<Edge>> copiedAdjacency = new LinkedHashMap<>();
        adjacency.forEach((node, edges) -> copiedAdjacency.put(node, List.copyOf(edges)));

        Map<String, Set<String>> copiedLines = new LinkedHashMap<>();
        stationLines.forEach((node, lines) -> copiedLines.put(node, Set.copyOf(lines)));

        return new RouteGraph(
                copiedNodes,
                Collections.unmodifiableMap(copiedAdjacency),
                Collections.unmodifiableMap(copiedLines));
    }

    /**
     * 전체 정점(역 ID) 수.
     */
    public int nodeCount() {
        return nodes.size();
    }

    /**
     * 전체 엣지 수.
     */
    public int edgeCount() {
        return adjacency.values().stream().mapToInt(List::size).sum();
    }

    /**
     * 전체 정점(역 ID) 목록. 불변이다.
     */
    public Set<String> nodes() {
        return nodes;
    }

    /**
     * 인접 리스트 전체. key = 출발 역 ID, value = 유향 엣지 목록. 불변이다.
     *
     * <p>다음 단계(최단 경로 탐색)가 그대로 사용하는 shape이다.
     */
    public Map<String, List<Edge>> adjacency() {
        return adjacency;
    }

    /**
     * 전체 엣지 목록.
     */
    public List<Edge> edges() {
        List<Edge> all = new ArrayList<>();
        adjacency.values().forEach(all::addAll);
        return List.copyOf(all);
    }

    /**
     * 주어진 역이 정점으로 존재하는지 확인한다.
     */
    public boolean containsNode(String stationId) {
        return nodes.contains(stationId);
    }

    /**
     * 출발 역에서 나가는 유향 엣지 목록.
     *
     * @param fromNode 출발 역 ID
     * @return 나가는 엣지 목록(없으면 빈 목록)
     */
    public List<Edge> outgoingEdges(String fromNode) {
        return adjacency.getOrDefault(fromNode, List.of());
    }

    /**
     * 출발·도착 방향 엣지 조회.
     *
     * <p>미등록 출발역이거나 해당 방향 엣지가 없으면 빈 값을 돌려준다
     * (부재를 정확히 보고하기 위해 부분 일치 예외를 던지지 않는다).
     *
     * @param fromNode 출발 역 ID
     * @param toNode 도착 역 ID
     * @return 해당 방향 엣지(없으면 빈 값)
     */
    public Optional<Edge> findEdge(String fromNode, String toNode) {
        return outgoingEdges(fromNode).stream()
                .filter(edge -> edge.toNode().equals(toNode))
                .findFirst();
    }

    /**
     * 주어진 수단만 남긴 하위 그래프를 새로 만든다(S15P21A104-185, 허용 수단 조합별 대체 후보 탐색용).
     *
     * <p>탐색 알고리즘({@link com.ssafy.s15p21a104.domain.route.finder.ShortestPathFinder})은
     * 손대지 않는다 — 같은 알고리즘을 여러 하위 그래프에 반복 적용해 조합별 후보를 얻는다.
     * 원본 그래프는 바꾸지 않는다(이 그래프도 불변).
     *
     * @param allowedModes 남길 수단 집합. 이 집합에 없는 수단의 엣지는 전부 제외한다
     * @return 허용 수단 엣지만으로 다시 조립한 그래프
     */
    public RouteGraph filterByModes(Set<TravelMode> allowedModes) {
        Set<String> filteredNodes = new LinkedHashSet<>();
        Map<String, List<Edge>> filteredAdjacency = new LinkedHashMap<>();
        Map<String, Set<String>> filteredLines = new LinkedHashMap<>();
        for (Edge edge : edges()) {
            if (!allowedModes.contains(edge.mode())) {
                continue;
            }
            filteredNodes.add(edge.fromNode());
            filteredNodes.add(edge.toNode());
            filteredAdjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>()).add(edge);
            filteredLines.computeIfAbsent(edge.fromNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
            filteredLines.computeIfAbsent(edge.toNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
        }
        return RouteGraph.of(filteredNodes, filteredAdjacency, filteredLines);
    }

    /**
     * 추가 엣지를 합친 새 그래프를 만든다(S15P21A104-187, 좌표 접근 임시 간선용).
     *
     * <p>원본 그래프는 바꾸지 않는다(이 그래프도 불변) — 요청마다 이 메서드로 새 그래프를
     * 만들어 쓰고 버리면, 공유 그래프(레지스트리가 들고 있는 원본)가 다른 요청의 좌표로
     * 오염되지 않는다.
     *
     * @param extraEdges 합칠 엣지 목록(예: 좌표→역 임시 WALK 엣지). null·빈 목록 허용
     * @return 기존 엣지 + 추가 엣지로 다시 조립한 그래프
     */
    public RouteGraph withExtraEdges(List<Edge> extraEdges) {
        if (extraEdges == null || extraEdges.isEmpty()) {
            return this;
        }
        Set<String> newNodes = new LinkedHashSet<>(nodes);
        Map<String, List<Edge>> newAdjacency = new LinkedHashMap<>();
        adjacency.forEach((node, edges) -> newAdjacency.put(node, new ArrayList<>(edges)));
        Map<String, Set<String>> newLines = new LinkedHashMap<>();
        stationLines.forEach((node, lines) -> newLines.put(node, new LinkedHashSet<>(lines)));

        for (Edge edge : extraEdges) {
            newNodes.add(edge.fromNode());
            newNodes.add(edge.toNode());
            newAdjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>()).add(edge);
            newLines.computeIfAbsent(edge.fromNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
            newLines.computeIfAbsent(edge.toNode(), key -> new LinkedHashSet<>()).add(edge.routeId());
        }
        return RouteGraph.of(newNodes, newAdjacency, newLines);
    }

    /**
     * 역(정점)의 소속 노선 집합.
     *
     * <p>역 하나가 여러 노선에 걸친 경우(예: st_B가 L2·L9 환승) {@code {L2, L9}}처럼
     * 엣지의 {@code routeId}에서 파생된 값이 돌아온다. 엣지가 하나도 없는 역은 빈 집합.
     *
     * @param stationId 역 ID
     * @return 소속 노선 ID 집합
     */
    public Set<String> linesOfStation(String stationId) {
        return stationLines.getOrDefault(stationId, Set.of());
    }
}
