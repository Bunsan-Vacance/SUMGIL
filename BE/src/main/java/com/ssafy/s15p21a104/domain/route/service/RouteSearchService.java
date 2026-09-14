package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.route.bike.BikeStockGate;
import com.ssafy.s15p21a104.domain.route.dto.request.CoordinateRouteSearchRequest;
import com.ssafy.s15p21a104.domain.route.dto.request.DepartureSlot;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePlaceRequest;
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
import com.ssafy.s15p21a104.domain.route.walk.geometry.WalkGeometryRegistry;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
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
    private final WalkGeometryRegistry walkGeometryRegistry;

    public List<RouteSearchResponse> search(
            String originStationId,
            String destStationId,
            List<TravelMode> modes,
            RoutePriority priority,
            LocalDateTime departureTime
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
        // 생략 시 현재 시각 기준. dow_type·time_slot 조회 키로 바꿔 대기시간 반영(96/104 후속, 전우석)에 넘긴다.
        DepartureSlot departureSlot = DepartureSlot.of(departureTime != null ? departureTime : LocalDateTime.now());
        return filterByModes(algorithmCandidates(graph, originStationId, destStationId, departureSlot), modes);
    }

    private List<RouteSearchResponse> algorithmCandidates(
            RouteGraph graph, String originStationId, String destStationId, DepartureSlot departureSlot) {
        // departureSlot은 이번 커밋(API 파라미터, S15P21A104-63)에서는 아직 안 쓴다 — 그래프 슬롯 선택과
        // 탑승 시 wait_sec 가산(96/104 후속, 전우석)이 붙으면 graph()/ShortestPathFinder 호출에 넘긴다.
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
                    transferSecs, graphRegistry.rentalIds());
            return response.map(this::withGeometry)
                    .filter(r -> BikeStockGate.passesEdges(
                            found.edges().stream().map(Edge::fromNode).toList(),
                            found.edges().stream().map(Edge::mode).toList(),
                            graphRegistry.bikeStock()))
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
        Optional<MultiLineStringResponse> geometry = leg.mode() == TravelMode.WALK
                ? walkGeometryRegistry.geometryFor(leg.fromNodeId(), leg.toNodeId(),
                        leg.fromLat(), leg.fromLng(), leg.toLat(), leg.toLng())
                : railGeometryRegistry.geometryForLeg(
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

    /**
     * 좌표 기반 통합 길찾기 진입점(S15P21A104-185). 이 티켓 범위는 요청 계약과 입력 검증까지다.
     *
     * <p>좌표를 실제 교통망(역·정류장·대여소)에 연결하는 접근 후보 탐색과 보행 계산은
     * 후속 작업의 책임이다(FE-좌표기반-통합길찾기-API-협의요청.md 6·7절). 유효한 요청이어도
     * 아직 {@link ErrorType#ACCESS_CANDIDATE_NOT_READY}를 반환한다 — 빈 배열로 조용히
     * "경로 없음"인 척하지 않고, 미구현 상태임을 명시적으로 알린다.
     *
     * @throws DomainException 좌표가 비어있거나 유효 범위를 벗어나면 {@link ErrorType#INVALID_COORDINATE},
     *         출발·도착 좌표가 완전히 같으면 {@link ErrorType#SAME_ORIGIN_DEST},
     *         입력이 유효하면 {@link ErrorType#ACCESS_CANDIDATE_NOT_READY}
     */
    public List<RouteSearchResponse> searchByCoordinate(CoordinateRouteSearchRequest request) {
        RoutePlaceRequest origin = requireValidPlace(request == null ? null : request.origin());
        RoutePlaceRequest destination = requireValidPlace(request == null ? null : request.destination());
        if (origin.lat().equals(destination.lat()) && origin.lng().equals(destination.lng())) {
            throw new DomainException(ErrorType.SAME_ORIGIN_DEST);
        }
        throw new DomainException(ErrorType.ACCESS_CANDIDATE_NOT_READY);
    }

    private RoutePlaceRequest requireValidPlace(RoutePlaceRequest place) {
        if (place == null || place.lat() == null || place.lng() == null) {
            throw new DomainException(ErrorType.INVALID_COORDINATE);
        }
        if (place.lat() < -90 || place.lat() > 90 || place.lng() < -180 || place.lng() > 180) {
            throw new DomainException(ErrorType.INVALID_COORDINATE);
        }
        return place;
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
