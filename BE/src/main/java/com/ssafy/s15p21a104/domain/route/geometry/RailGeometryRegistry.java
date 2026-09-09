package com.ssafy.s15p21a104.domain.route.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.entity.RailLinkGeometry;
import com.ssafy.s15p21a104.domain.route.entity.RailNode;
import com.ssafy.s15p21a104.domain.route.repository.RailLinkGeometryRepository;
import com.ssafy.s15p21a104.domain.route.repository.RailNodeRepository;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * KTDB geometry 인메모리 보관소. 기동 시 {@code rail_node}·{@code rail_link_geometry}를 1회 로드한다.
 *
 * <p>{@link com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry}와 같은 패턴이다 — 탐색마다
 * DB를 다시 조회하지 않는다. 적재 전(테이블 비어 있음)에는 빈 상태로 뜨고, 조회 측은 "매칭 안 됨"으로
 * 처리한다(예외를 던지지 않는다).
 */
@Slf4j
@Component
public class RailGeometryRegistry {

    /** 역 좌표와 KTDB 노드 좌표가 이 거리보다 멀면 매칭하지 않는다 — 엉뚱한 노드에 잘못 붙는 것을 막는다. */
    private static final double MAX_NODE_MATCH_METERS = 300;

    private final RailNodeRepository railNodeRepository;
    private final RailLinkGeometryRepository railLinkGeometryRepository;

    private List<RailNode> nodes = List.of();
    private Map<String, List<RailLinkGeometry>> linksByLineId = Map.of();

    public RailGeometryRegistry(RailNodeRepository railNodeRepository,
                                 RailLinkGeometryRepository railLinkGeometryRepository) {
        this.railNodeRepository = railNodeRepository;
        this.railLinkGeometryRepository = railLinkGeometryRepository;
    }

    @PostConstruct
    void load() {
        nodes = railNodeRepository.findAll();
        Map<String, List<RailLinkGeometry>> byLine = new HashMap<>();
        for (RailLinkGeometry link : railLinkGeometryRepository.findAll()) {
            if (link.getLineId() == null) {
                continue;
            }
            byLine.computeIfAbsent(link.getLineId(), key -> new ArrayList<>()).add(link);
        }
        linksByLineId = Map.copyOf(byLine);
        log.info("KTDB geometry 로드 완료: node {}개, 매칭된 line {}개, link {}개",
                nodes.size(), linksByLineId.size(),
                linksByLineId.values().stream().mapToInt(List::size).sum());
    }

    /** 좌표로 가장 가까운 KTDB 노드를 찾는다. {@link #MAX_NODE_MATCH_METERS} 밖이면 매칭하지 않는다. */
    public Optional<String> nearestNodeId(double lat, double lng) {
        String bestId = null;
        double bestDistance = Double.MAX_VALUE;
        for (RailNode node : nodes) {
            double distance = GeoDistance.haversineMeters(lat, lng, node.getLat(), node.getLng());
            if (distance < bestDistance) {
                bestDistance = distance;
                bestId = node.getNodeId();
            }
        }
        if (bestId == null || bestDistance > MAX_NODE_MATCH_METERS) {
            return Optional.empty();
        }
        return Optional.of(bestId);
    }

    /** 노선 하나에 속한 KTDB link 전체. 매칭 안 되는 노선(line_id null)이나 미적재 시 빈 리스트. */
    public List<RailLinkGeometry> linksForLine(String lineId) {
        return linksByLineId.getOrDefault(lineId, List.of());
    }

    /**
     * 구간(leg) 양 끝 좌표로 KTDB 노드를 각각 찾고, 같은 노선 안에서 두 노드를 잇는 link 체인을 찾아
     * MultiLineString으로 합친다. 역 좌표 매칭 실패나 link 미연결이면 빈 값 — 호출자가 "unavailable" 처리.
     */
    public Optional<MultiLineStringResponse> geometryForLeg(
            String lineId, double fromLat, double fromLng, double toLat, double toLng) {
        if (lineId == null) {
            return Optional.empty();
        }
        List<RailLinkGeometry> lineLinks = linksForLine(lineId);
        if (lineLinks.isEmpty()) {
            return Optional.empty();
        }
        Optional<String> fromNodeId = nearestNodeId(fromLat, fromLng);
        Optional<String> toNodeId = nearestNodeId(toLat, toLng);
        if (fromNodeId.isEmpty() || toNodeId.isEmpty()) {
            return Optional.empty();
        }
        Optional<List<RailLinkPathFinder.Step>> path =
                RailLinkPathFinder.find(lineLinks, fromNodeId.get(), toNodeId.get());
        if (path.isEmpty()) {
            return Optional.empty();
        }
        List<List<List<Double>>> coordinates = path.get().stream()
                .map(RailLinkPathFinder.Step::coordinates)
                .toList();
        if (coordinates.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(MultiLineStringResponse.of(coordinates));
    }
}
