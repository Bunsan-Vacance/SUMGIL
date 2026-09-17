package com.ssafy.s15p21a104.load.subway;

import com.ssafy.s15p21a104.load.Coords;
import com.ssafy.s15p21a104.load.ValidationReport;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 스키마가 강제하지 않는 규칙을 적재 전에 검증한다 (BE/docs/db/schema.md "모드-노드 규칙").
 * 오류가 하나라도 있으면 적재하지 않는다. 표본이 없는 값을 채워 넣지 않는 것도 여기서 지킨다 — 좌표 없음은 경고일 뿐이다.
 */
public final class LoadValidator {

    // 좌표 범위 규칙은 마스터 3종과 공유한다 (load.Coords). 밖이면 좌표 열이 뒤바뀐 것 같은 파싱 오류다.
    private LoadValidator() {
    }

    public static ValidationReport validate(SubwayGraph graph) {
        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();

        Set<String> stationIds = graph.stations().stream().map(StationRow::stationId).collect(Collectors.toSet());
        Set<String> lineIds = graph.lines().stream().map(LineRow::lineId).collect(Collectors.toSet());

        for (StationRow s : graph.stations()) {
            if (s.lat() == null || s.lng() == null) {
                warnings.add("좌표 없음: " + s.stationId());
            } else if (!Coords.inMetroArea(s.lat(), s.lng())) {
                errors.add("좌표가 수도권 범위 밖: " + s.stationId() + " (" + s.lat() + ", " + s.lng() + ")");
            }
        }

        for (EdgeRow e : graph.edges()) {
            String label = e.routeId() + " " + e.fromNode() + "→" + e.toNode();
            if (e.fromNode().equals(e.toNode())) {
                errors.add("출발과 도착이 같은 엣지: " + label);
                continue;
            }
            if (e.travelSec() <= 0) {
                errors.add("이동 초가 0 이하: " + label);
            }
            if (!stationIds.contains(e.fromNode())) {
                errors.add("존재하지 않는 출발 역: " + e.fromNode() + " (" + label + ")");
            }
            if (!stationIds.contains(e.toNode())) {
                errors.add("존재하지 않는 도착 역: " + e.toNode() + " (" + label + ")");
            }
            if (!lineIds.contains(e.routeId())) {
                errors.add("적재되지 않은 노선을 route_id 로 사용: " + label);
            }
        }

        for (TransferMetaRow t : graph.transfers()) {
            if (!stationIds.contains(t.stationId())) {
                warnings.add("환승 정보의 역이 구간에 없음: " + t.stationId() + " " + t.fromLine() + "→" + t.toLine());
            }
            if (t.walkSec() <= 0) {
                errors.add("환승 도보 초가 0 이하: " + t.stationId() + " " + t.fromLine() + "→" + t.toLine());
            }
        }

        warnings.addAll(disconnectedLines(graph));
        return new ValidationReport(errors, warnings);
    }

    /**
     * 노선별로 엣지가 하나의 연결 요소를 이루는지 본다. 둘 이상이면 원천에 구간이 빠진 것이다.
     * 오류가 아니라 경고인 이유: 부분 데이터라도 이어진 구간 안에서는 탐색이 가능하고, 없는 구간을 만들어 넣지는 않기 때문이다.
     */
    private static List<String> disconnectedLines(SubwayGraph graph) {
        Map<String, Map<String, Set<String>>> adjacencyByLine = new LinkedHashMap<>();
        for (EdgeRow e : graph.edges()) {
            if (e.fromNode().equals(e.toNode())) {
                continue;
            }
            Map<String, Set<String>> adjacency = adjacencyByLine.computeIfAbsent(e.routeId(), k -> new LinkedHashMap<>());
            adjacency.computeIfAbsent(e.fromNode(), k -> new LinkedHashSet<>()).add(e.toNode());
            adjacency.computeIfAbsent(e.toNode(), k -> new LinkedHashSet<>()).add(e.fromNode());
        }

        List<String> warnings = new ArrayList<>();
        for (Map.Entry<String, Map<String, Set<String>>> entry : adjacencyByLine.entrySet()) {
            List<Integer> componentSizes = componentSizes(entry.getValue());
            if (componentSizes.size() > 1) {
                warnings.add("노선 " + entry.getKey() + " 의 구간이 " + componentSizes.size() + "개 조각으로 끊겨 있음 (역 수: "
                        + componentSizes + ") — 원천에 구간 누락");
            }
        }
        return warnings;
    }

    private static List<Integer> componentSizes(Map<String, Set<String>> adjacency) {
        Set<String> visited = new HashSet<>();
        List<Integer> sizes = new ArrayList<>();
        for (String start : adjacency.keySet()) {
            if (!visited.add(start)) {
                continue;
            }
            int size = 0;
            Deque<String> stack = new ArrayDeque<>(List.of(start));
            while (!stack.isEmpty()) {
                String node = stack.pop();
                size++;
                for (String next : adjacency.getOrDefault(node, Set.of())) {
                    if (visited.add(next)) {
                        stack.push(next);
                    }
                }
            }
            sizes.add(size);
        }
        return sizes;
    }
}
