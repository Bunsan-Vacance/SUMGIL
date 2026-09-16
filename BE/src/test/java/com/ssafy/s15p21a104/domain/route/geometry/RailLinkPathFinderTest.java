package com.ssafy.s15p21a104.domain.route.geometry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.RailLinkGeometry;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * BFS 경로 탐색 + link 저장 방향과 실제 탐색 방향이 반대일 때 좌표를 뒤집는지 검증한다.
 */
class RailLinkPathFinderTest {

    private RailLinkGeometry link(String linkId, String fromNodeId, String toNodeId, double... coords) {
        StringBuilder json = new StringBuilder("{\"type\":\"LineString\",\"coordinates\":[");
        for (int i = 0; i < coords.length; i += 2) {
            if (i > 0) {
                json.append(",");
            }
            json.append("[").append(coords[i]).append(",").append(coords[i + 1]).append("]");
        }
        json.append("]}");
        return new RailLinkGeometry(linkId, fromNodeId, toNodeId, "1002", json.toString());
    }

    @Test
    @DisplayName("정방향으로 저장된 link 두 개를 순서대로 잇는다")
    void 정방향_두구간_연결() {
        List<RailLinkGeometry> links = List.of(
                link("L1", "A", "B", 0, 0, 1, 1),
                link("L2", "B", "C", 1, 1, 2, 2));

        Optional<List<RailLinkPathFinder.Step>> result = RailLinkPathFinder.find(links, "A", "C");

        assertTrue(result.isPresent());
        List<RailLinkPathFinder.Step> steps = result.get();
        assertEquals(2, steps.size());
        assertEquals(List.of(List.of(0.0, 0.0), List.of(1.0, 1.0)), steps.get(0).coordinates());
        assertEquals(List.of(List.of(1.0, 1.0), List.of(2.0, 2.0)), steps.get(1).coordinates());
    }

    @Test
    @DisplayName("link 저장 방향과 반대로 탐색하면 좌표 배열을 뒤집는다")
    void 역방향_탐색시_좌표_반전() {
        // link는 C -> A로 저장되어 있는데, 탐색은 A -> C 방향으로 한다.
        List<RailLinkGeometry> links = List.of(link("L1", "C", "A", 2, 2, 0, 0));

        Optional<List<RailLinkPathFinder.Step>> result = RailLinkPathFinder.find(links, "A", "C");

        assertTrue(result.isPresent());
        assertEquals(1, result.get().size());
        assertEquals(List.of(List.of(0.0, 0.0), List.of(2.0, 2.0)), result.get().get(0).coordinates());
    }

    @Test
    @DisplayName("두 노드가 연결되어 있지 않으면 빈 값")
    void 연결_안되면_empty() {
        List<RailLinkGeometry> links = List.of(link("L1", "A", "B", 0, 0, 1, 1));

        Optional<List<RailLinkPathFinder.Step>> result = RailLinkPathFinder.find(links, "A", "Z");

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("출발지와 도착지가 같으면 빈 경로(link 0개)")
    void 출발지와_도착지가_같으면_빈경로() {
        List<RailLinkGeometry> links = List.of(link("L1", "A", "B", 0, 0, 1, 1));

        Optional<List<RailLinkPathFinder.Step>> result = RailLinkPathFinder.find(links, "A", "A");

        assertTrue(result.isPresent());
        assertTrue(result.get().isEmpty());
    }
}
