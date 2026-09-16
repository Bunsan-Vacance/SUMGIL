package com.ssafy.s15p21a104.domain.route.geometry;

import com.ssafy.s15p21a104.domain.route.entity.RailLinkGeometry;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * 노선 하나에 속한 KTDB link들 사이에서 두 노드를 잇는 경로를 찾는다(BFS, 가중치 없음 — link 개수 최소화).
 *
 * <p>DB·Spring에 의존하지 않는 순수 함수다. {@link RailGeometryRegistry#linksForLine}으로 뽑은 노선 하나
 * 분량의 link 목록을 받아 동작한다.</p>
 */
final class RailLinkPathFinder {

    private RailLinkPathFinder() {
    }

    /** 경로 위 link 하나 — 실제 탐색 방향으로 이미 뒤집힌 좌표(GeoJSON [lng, lat] 순서 그대로). */
    record Step(String linkId, List<List<Double>> coordinates) {
    }

    /** BFS 확장을 위해 두 방향(정방향/역방향) 모두 인접 리스트에 넣는다. */
    private record Traversal(RailLinkGeometry link, String toNodeId, boolean reversed) {
    }

    static Optional<List<Step>> find(List<RailLinkGeometry> lineLinks, String fromNodeId, String toNodeId) {
        if (fromNodeId.equals(toNodeId)) {
            return Optional.of(List.of());
        }

        Map<String, List<Traversal>> adjacency = new HashMap<>();
        for (RailLinkGeometry link : lineLinks) {
            adjacency.computeIfAbsent(link.getFromNodeId(), key -> new ArrayList<>())
                    .add(new Traversal(link, link.getToNodeId(), false));
            adjacency.computeIfAbsent(link.getToNodeId(), key -> new ArrayList<>())
                    .add(new Traversal(link, link.getFromNodeId(), true));
        }

        Map<String, Traversal> cameFrom = new HashMap<>();
        Set<String> visited = new HashSet<>();
        Deque<String> queue = new ArrayDeque<>();
        visited.add(fromNodeId);
        queue.add(fromNodeId);

        while (!queue.isEmpty()) {
            String current = queue.poll();
            if (current.equals(toNodeId)) {
                break;
            }
            for (Traversal step : adjacency.getOrDefault(current, List.of())) {
                if (visited.add(step.toNodeId())) {
                    cameFrom.put(step.toNodeId(), step);
                    queue.add(step.toNodeId());
                }
            }
        }
        if (!visited.contains(toNodeId)) {
            return Optional.empty();
        }

        List<Traversal> reversePath = new ArrayList<>();
        String node = toNodeId;
        while (!node.equals(fromNodeId)) {
            Traversal step = cameFrom.get(node);
            if (step == null) {
                return Optional.empty();
            }
            reversePath.add(step);
            node = step.reversed() ? step.link().getToNodeId() : step.link().getFromNodeId();
        }

        List<Step> path = new ArrayList<>(reversePath.size());
        for (int i = reversePath.size() - 1; i >= 0; i--) {
            Traversal step = reversePath.get(i);
            List<List<Double>> coordinates = RailGeometryJson.coordinates(step.link());
            if (step.reversed()) {
                List<List<Double>> reversed = new ArrayList<>(coordinates);
                java.util.Collections.reverse(reversed);
                coordinates = reversed;
            }
            path.add(new Step(step.link().getLinkId(), coordinates));
        }
        return Optional.of(path);
    }
}
