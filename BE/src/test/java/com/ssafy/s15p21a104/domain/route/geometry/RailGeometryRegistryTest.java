package com.ssafy.s15p21a104.domain.route.geometry;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.entity.RailLinkGeometry;
import com.ssafy.s15p21a104.domain.route.entity.RailNode;
import com.ssafy.s15p21a104.domain.route.repository.RailLinkGeometryRepository;
import com.ssafy.s15p21a104.domain.route.repository.RailNodeRepository;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * 서울역처럼 여러 노선의 KTDB 노드가 아주 가까이 모여 있을 때, 좌표상 "전체에서 가장 가까운 노드"가
 * 아니라 "찾는 노선 소속 노드 중 가장 가까운 노드"를 골라야 한다는 걸 검증한다(실제 버그 재현).
 */
@ExtendWith(MockitoExtension.class)
class RailGeometryRegistryTest {

    @Mock
    private RailNodeRepository railNodeRepository;

    @Mock
    private RailLinkGeometryRepository railLinkGeometryRepository;

    private RailGeometryRegistry registry(List<RailNode> nodes, List<RailLinkGeometry> links) {
        when(railNodeRepository.findAll()).thenReturn(nodes);
        when(railLinkGeometryRepository.findAll()).thenReturn(links);
        RailGeometryRegistry registry = new RailGeometryRegistry(railNodeRepository, railLinkGeometryRepository);
        registry.load();
        return registry;
    }

    private RailLinkGeometry link(String linkId, String fromNodeId, String toNodeId, String lineId,
                                   double... coords) {
        StringBuilder json = new StringBuilder("{\"type\":\"LineString\",\"coordinates\":[");
        for (int i = 0; i < coords.length; i += 2) {
            if (i > 0) {
                json.append(",");
            }
            json.append("[").append(coords[i]).append(",").append(coords[i + 1]).append("]");
        }
        json.append("]}");
        return new RailLinkGeometry(linkId, fromNodeId, toNodeId, lineId, json.toString());
    }

    @Test
    @DisplayName("다른 노선의 더 가까운 노드가 있어도, 찾는 노선 소속 노드를 고른다")
    void 노선_소속_노드만_후보로_삼는다() {
        // 4호선 노드가 역 좌표(37.5, 127.0)에서 더 가깝고(10m 안쪽), 경의중앙선(1063) 노드는 조금 더 멀다.
        RailNode line4Node = new RailNode("N4", 37.50005, 127.0, "서울역(4호선)");
        RailNode line1063Node = new RailNode("N1063", 37.5040, 127.0, "서울역(경의)");
        RailNode farNode = new RailNode("N1063B", 37.55, 127.05, "먼역");

        RailLinkGeometry link1063 = link("L1", "N1063", "N1063B", "1063", 127.0, 37.5040, 127.05, 37.55);

        RailGeometryRegistry registry = registry(List.of(line4Node, line1063Node, farNode), List.of(link1063));

        Optional<MultiLineStringResponse> result =
                registry.geometryForLeg("1063", 37.5, 127.0, 37.55, 127.05);

        assertTrue(result.isPresent());
    }

    @Test
    @DisplayName("노선 소속 노드가 매칭 거리 밖이면 unavailable")
    void 매칭거리_밖이면_empty() {
        RailNode farLine1063Node = new RailNode("N1063", 40.0, 130.0, "먼 경의역");
        RailLinkGeometry link1063 = link("L1", "N1063", "N1063B", "1063", 130.0, 40.0, 130.1, 40.1);

        RailGeometryRegistry registry = registry(List.of(farLine1063Node), List.of(link1063));

        Optional<MultiLineStringResponse> result =
                registry.geometryForLeg("1063", 37.5, 127.0, 37.55, 127.05);

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("역 좌표가 null이면 매칭하지 않는다는 계약과 별개로, lineId가 없으면 즉시 empty")
    void lineId_없으면_empty() {
        RailGeometryRegistry registry = registry(List.of(), List.of());

        lenient().when(railNodeRepository.findAll()).thenReturn(List.of());
        Optional<MultiLineStringResponse> result = registry.geometryForLeg(null, 37.5, 127.0, 37.55, 127.05);

        assertTrue(result.isEmpty());
    }
}
