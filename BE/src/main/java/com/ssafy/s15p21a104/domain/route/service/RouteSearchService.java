package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.route.bike.BikeStockGate;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePriority;
import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.finder.ShortestPathFinder;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * 경로 검색. 그래프 미적재 시 빈 배열(경로 없음)로 응답한다. 가짜 후보를 만들지 않는다.
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class RouteSearchService {

    private final StationRepository stationRepository;
    private final RouteGraphRegistry graphRegistry;
    private final TransferRule transferRule;
    private final RailGeometryRegistry railGeometryRegistry;

    public List<RouteSearchResponse> search(
            String originStationId,
            String destStationId,
            List<TravelMode> modes,
            RoutePriority priority
    ) {
        if (originStationId.equals(destStationId)) {
            throw new DomainException(ErrorType.SAME_ORIGIN_DEST);
        }

        // 그래프 미로드(미적재) 시 빈 배열(경로 없음)로 응답한다. 가짜 후보를 만들지 않는다.
        RouteGraph graph = graphRegistry == null ? null : graphRegistry.graph();
        if (graph == null) {
            return List.of();
        }

        findStation(originStationId);
        findStation(destStationId);
        return filterByModes(algorithmCandidates(graph, originStationId, destStationId), modes);
    }

    private List<RouteSearchResponse> algorithmCandidates(
            RouteGraph graph, String originStationId, String destStationId) {
        try {
            // 탐색과 leg 표시에 같은 규칙(실측 우선)을 쓴다. 합계와 leg 합이 어긋나지 않는다.
            TransferRule rule = transferRule.withTable(graphRegistry.transferTimes());
            FoundPath found = new ShortestPathFinder(rule).find(graph, originStationId, destStationId);
            List<RouteMapper.EngineSegment> segments = found.edges().stream()
                    .map(edge -> new RouteMapper.EngineSegment(
                            edge.fromNode(), edge.toNode(), edge.routeId(), edge.travelSec(),
                            edge.mode()))
                    .toList();
            // 노선 전환 경계마다 환승 소요를 같은 규칙으로 매긴다.
            List<Long> transferSecs = new ArrayList<>();
            String currentLine = null;
            for (Edge edge : found.edges()) {
                if (currentLine != null && !currentLine.equals(edge.routeId())) {
                    transferSecs.add(rule.costWithStation(
                            0, edge.fromNode(), currentLine, edge.routeId()));
                }
                currentLine = edge.routeId();
            }
            Optional<RouteSearchResponse> response = RouteMapper.toResponseWithTransfers(
                    new RouteMapper.EnginePath(segments, found.totalSec(), found.transferCount()),
                    graphRegistry.stationInfos(), RouteType.SHORTEST, RouteSource.ALGORITHM,
                    transferSecs);
            return response.map(this::withGeometry)
                    .filter(r -> BikeStockGate.passes(r.legs(), graphRegistry.bikeStock()))
                    .map(List::of).orElseGet(List::of);
        } catch (DomainException exception) {
            if (exception.getErrorType() == ErrorType.ROUTE_NOT_FOUND) {
                return List.of();
            }
            throw exception;
        }
    }

    /**
     * KTDB 실선로 geometry를 구간(leg)마다 붙인다. RouteMapper는 DB에 의존하지 않으므로
     * (순수 함수 유지) geometry 부착은 여기서 후처리로 한다 — 미승인 필드, README 참고.
     */
    private RouteSearchResponse withGeometry(RouteSearchResponse response) {
        List<RouteLegResponse> legs = response.legs().stream()
                .map(this::withGeometry)
                .toList();
        return new RouteSearchResponse(response.routeType(), response.totalMinutes(), legs, response.source());
    }

    private RouteLegResponse withGeometry(RouteLegResponse leg) {
        if (leg.fromLat() == null || leg.fromLng() == null || leg.toLat() == null || leg.toLng() == null) {
            return leg;
        }
        Optional<MultiLineStringResponse> geometry = railGeometryRegistry.geometryForLeg(
                leg.routeId(), leg.fromLat(), leg.fromLng(), leg.toLat(), leg.toLng());
        if (geometry.isEmpty()) {
            return leg;
        }
        return new RouteLegResponse(
                leg.mode(),
                leg.fromNodeId(), leg.fromNodeName(), leg.fromLat(), leg.fromLng(),
                leg.toNodeId(), leg.toNodeName(), leg.toLat(), leg.toLng(),
                leg.routeId(), leg.minutes(),
                geometry.get(), "available"
        );
    }

    private Station findStation(String stationId) {
        return stationRepository.findById(stationId)
                .orElseThrow(() -> new DomainException(ErrorType.STATION_NOT_FOUND));
    }

    private List<RouteSearchResponse> filterByModes(List<RouteSearchResponse> candidates, List<TravelMode> modes) {
        if (modes == null || modes.isEmpty()) {
            return candidates;
        }
        return candidates.stream()
                .filter(candidate -> candidate.legs().stream()
                        .allMatch(leg -> isAlwaysAllowed(leg.mode()) || modes.contains(leg.mode())))
                .toList();
    }

    private boolean isAlwaysAllowed(TravelMode mode) {
        return mode == TravelMode.WALK || mode == TravelMode.TRANSFER;
    }
}
