package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.bus.entity.BusRoute;
import com.ssafy.s15p21a104.domain.bus.repository.BusRouteRepository;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionRepository;
import com.ssafy.s15p21a104.domain.route.bike.geometry.BikeGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.dto.request.CoordinateRouteSearchRequest;
import com.ssafy.s15p21a104.domain.route.dto.request.DepartureSlot;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePlaceRequest;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePriority;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RouteGeometryEnhancer;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.route.scoring.RouteScoreRanker;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.walk.geometry.WalkGeometryRegistry;
import com.ssafy.s15p21a104.domain.station.entity.Line;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 경로 검색. 그래프 미적재 시 빈 배열(경로 없음)로 응답한다. 가짜 후보를 만들지 않는다.
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class RouteSearchService {

    /** 응답에 담을 후보 수 상한(S15P21A104-185). */
    private static final int MAX_CANDIDATES = 10;

    private final StationRepository stationRepository;
    private final RouteGraphRegistry graphRegistry;
    private final TransferRule transferRule;
    private final RailGeometryRegistry railGeometryRegistry;
    private final WalkGeometryRegistry walkGeometryRegistry;
    private final BikeGeometryRegistry bikeGeometryRegistry;
    private final RouteLineRepository routeLineRepository;
    private final BusRouteRepository busRouteRepository;
    private final CongestionRepository congestionRepository;

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

        // 그래프 미적재는 "경로 없음"(빈 배열)과 다른 상태다 — FE-175 항목9 지적사항.
        // 데이터가 아예 없어서 계산 자체를 못 한 것이므로 503으로 구분해 알린다.
        RouteGraph graph = graphRegistry == null ? null : graphRegistry.graph();
        if (graph == null) {
            throw new DomainException(ErrorType.ROUTE_DATA_NOT_READY);
        }

        findStation(originStationId);
        findStation(destStationId);
        // 생략 시 현재 시각 기준. dow_type·time_slot 조회 키로 바꿔 대기시간 반영(96/104 후속, 전우석)에 넘긴다.
        DepartureSlot departureSlot = DepartureSlot.of(departureTime != null ? departureTime : LocalDateTime.now());
        // 213 T4: 탐색→매핑 조립은 RouteCandidateFinder, geometry는 RouteGeometryEnhancer,
        // 쾌적 재정렬은 RouteScoreRanker에 위임. 서비스는 조립만 한다.
        List<RouteSearchResponse> candidates = candidateFinder().findCandidates(
                graph, originStationId, destStationId, MAX_CANDIDATES);
        List<RouteSearchResponse> withGeometry = withGeometryAll(candidates);
        // FE 175 지적사항: modes 필터는 routeType을 매긴 "뒤"에 걸리므로, 필터로 SHORTEST가
        // 빠지면 남은 후보 중 가장 빠른 게 ALTERNATIVE인 채로 나갈 수 있었다. 필터링 다음에
        // 다시 매겨 첫 번째가 항상 SHORTEST가 되도록 한다. routeName은 DB 조회가 필요해
        // 후보 수가 줄어든 다음(필터+재라벨링 이후)에 배치로 붙인다(FE-175 항목8).
        List<RouteSearchResponse> ranked = RouteCandidateFinder.relabelByRank(
                RouteCandidateFinder.filterByModes(withGeometry, modes));
        // priority=COMFORT가 아니면 순서·라벨을 전혀 건드리지 않는다(S15P21A104-157 AC2, 회귀 없음).
        if (priority == RoutePriority.COMFORT) {
            ranked = applyComfort(ranked, departureSlot);
        }
        return withRouteNames(ranked);
    }

    /** 탐색→매핑 조립기. 레지스트리 값을 주입해 만든다. */
    private RouteCandidateFinder candidateFinder() {
        return new RouteCandidateFinder(
                transferRule,
                graphRegistry.transferTimes(),
                graphRegistry.rentalIds(),
                graphRegistry.stationInfos(),
                graphRegistry::bikeStock);
    }

    /**
     * 쾌적 우선 재정렬(213 T4). {@link RouteScoreRanker}에 위임하고 서비스는
     * 혼잡도 조회 함수만 넘긴다.
     */
    private List<RouteSearchResponse> applyComfort(
            List<RouteSearchResponse> candidates, DepartureSlot departureSlot) {
        return new RouteScoreRanker(
                (targetType, targetId, dowType, timeSlot) -> congestionRepository
                        .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                                CongestionTarget.LINE, targetId, dowType, timeSlot)
                        .map(c -> c.getLevel().doubleValue())
                        .orElse(null))
                .applyComfort(candidates, departureSlot.dowType(), departureSlot.timeSlot());
    }

    /**
     * 후보 목록에 geometry를 붙인다(213 T3). {@link RouteGeometryEnhancer}가 후보별
     * 병렬 후처리 + 순서 보장 + 실패 격리를 맡는다. 서비스는 레지스트리 조회 함수만 넘긴다.
     */
    private List<RouteSearchResponse> withGeometryAll(List<RouteSearchResponse> candidates) {
        return new RouteGeometryEnhancer(
                (routeId, fromLat, fromLng, toLat, toLng) -> railGeometryRegistry.geometryForLeg(
                        routeId, fromLat, fromLng, toLat, toLng),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> walkGeometryRegistry.geometryFor(
                        fromId, toId, fromLat, fromLng, toLat, toLng),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> bikeGeometryRegistry.geometryFor(
                        fromId, toId, fromLat, fromLng, toLat, toLng))
                .enhanceAll(candidates);
    }

    /**
     * 사람이 읽는 노선 이름을 배치로 붙인다(FE-175 항목8). SUBWAY는 {@code line.name},
     * BUS는 {@code bus_route.name} — 그 외 수단은 의미 있는 노선명이 없어 null로 둔다.
     */
    private List<RouteSearchResponse> withRouteNames(List<RouteSearchResponse> responses) {
        Set<String> subwayLineIds = new HashSet<>();
        Set<String> busRouteIds = new HashSet<>();
        for (RouteSearchResponse response : responses) {
            for (RouteLegResponse leg : response.legs()) {
                if (leg.routeId() == null) {
                    continue;
                }
                if (leg.mode() == TravelMode.SUBWAY) {
                    subwayLineIds.add(leg.routeId());
                } else if (leg.mode() == TravelMode.BUS) {
                    busRouteIds.add(leg.routeId());
                }
            }
        }
        Map<String, String> lineNames = new HashMap<>();
        for (Line line : routeLineRepository.findAllById(subwayLineIds)) {
            lineNames.put(line.getLineId(), line.getName());
        }
        Map<String, String> busNames = new HashMap<>();
        for (BusRoute busRoute : busRouteRepository.findAllById(busRouteIds)) {
            busNames.put(busRoute.getRouteId(), busRoute.getName());
        }

        List<RouteSearchResponse> named = new ArrayList<>();
        for (RouteSearchResponse response : responses) {
            List<RouteLegResponse> legs = response.legs().stream()
                    .map(leg -> withRouteName(leg, lineNames, busNames))
                    .toList();
            named.add(new RouteSearchResponse(
                    response.routeType(), response.totalMinutes(), legs, response.source(),
                    response.totalDistanceMeters(), response.transferCount()));
        }
        return named;
    }

    private RouteLegResponse withRouteName(
            RouteLegResponse leg, Map<String, String> lineNames, Map<String, String> busNames) {
        String routeName = switch (leg.mode()) {
            case SUBWAY -> lineNames.get(leg.routeId());
            case BUS -> busNames.get(leg.routeId());
            default -> null;
        };
        if (routeName == null) {
            return leg;
        }
        return new RouteLegResponse(
                leg.mode(),
                leg.fromNodeId(), leg.fromNodeName(), leg.fromLat(), leg.fromLng(),
                leg.toNodeId(), leg.toNodeName(), leg.toLat(), leg.toLng(),
                leg.routeId(), leg.minutes(),
                leg.geometry(), leg.geometryStatus(),
                leg.distanceMeters(), routeName
        );
    }

    /** 좌표 검색 전용 임시 노드 ID(S15P21A104-187). 요청 하나 안에서만 쓰고 그래프에 남기지 않는다. */
    private static final String PLACE_ORIGIN_ID = "PLACE-ORIGIN";

    private static final String PLACE_DEST_ID = "PLACE-DEST";

    /** 좌표→역·정류장·대여소 접근 간선 연결 반경(m). {@link com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder}와 같은 값. */
    private static final double ACCESS_RADIUS_M = 500.0;

    /** 접근 후보 상한(가까운 순). 무제한 탐색을 막아 탐색량을 억제한다(S15P21A104-187 완료기준). */
    private static final int MAX_ACCESS_CANDIDATES = 5;

    /**
     * 좌표 기반 통합 길찾기 진입점(S15P21A104-185/187).
     *
     * <p>일반 장소(건물 등)는 역 DB에 없으므로, 좌표 주변 보행 접근 가능한 역·정류장·대여소를
     * 찾아 임시 WALK 간선으로 이어 붙인 뒤(요청마다 새로 만들고 버리는 그래프라 공유 그래프를
     * 오염시키지 않는다, {@link RouteGraph#withExtraEdges}) 같은 탐색·후보 파이프라인
     * ({@link #algorithmCandidates})을 그대로 태운다. 최단경로 알고리즘·기존 역 검색 경로는
     * 건드리지 않는다.
     *
     * @throws DomainException 좌표가 비어있거나 유효 범위를 벗어나면 {@link ErrorType#INVALID_COORDINATE},
     *         출발·도착 좌표가 완전히 같으면 {@link ErrorType#SAME_ORIGIN_DEST},
     *         그래프 미적재면 {@link ErrorType#ROUTE_DATA_NOT_READY},
     *         출발·도착 어느 한쪽이라도 반경 안에 접근 가능한 후보가 없으면
     *         {@link ErrorType#ACCESS_CANDIDATE_NOT_FOUND}
     */
    public List<RouteSearchResponse> searchByCoordinate(CoordinateRouteSearchRequest request) {
        RoutePlaceRequest origin = requireValidPlace(request == null ? null : request.origin());
        RoutePlaceRequest destination = requireValidPlace(request == null ? null : request.destination());
        if (origin.lat().equals(destination.lat()) && origin.lng().equals(destination.lng())) {
            throw new DomainException(ErrorType.SAME_ORIGIN_DEST);
        }

        RouteGraph graph = graphRegistry == null ? null : graphRegistry.graph();
        if (graph == null) {
            throw new DomainException(ErrorType.ROUTE_DATA_NOT_READY);
        }

        Map<String, RouteMapper.StationInfo> baseInfos = graphRegistry.stationInfos();
        List<Edge> originAccessEdges = accessEdges(PLACE_ORIGIN_ID, origin, baseInfos, graph, true);
        List<Edge> destAccessEdges = accessEdges(PLACE_DEST_ID, destination, baseInfos, graph, false);
        if (originAccessEdges.isEmpty() || destAccessEdges.isEmpty()) {
            throw new DomainException(ErrorType.ACCESS_CANDIDATE_NOT_FOUND);
        }

        List<Edge> accessEdges = new ArrayList<>(originAccessEdges);
        accessEdges.addAll(destAccessEdges);
        // 원본 그래프에 접근 임시 엣지만 얹는다 (213 T2: 7조합 반복 대신 1회 탐색).
        // withExtraEdges 자체도 얕은 복사라 안 건드리는 노드는 복사하지 않는다.
        RouteGraph augmentedGraph = graph.withExtraEdges(accessEdges);

        Map<String, RouteMapper.StationInfo> stationInfos = new HashMap<>(baseInfos);
        stationInfos.put(PLACE_ORIGIN_ID, new RouteMapper.StationInfo(
                PLACE_ORIGIN_ID, origin.name(), origin.lat(), origin.lng()));
        stationInfos.put(PLACE_DEST_ID, new RouteMapper.StationInfo(
                PLACE_DEST_ID, destination.name(), destination.lat(), destination.lng()));

        DepartureSlot departureSlot = DepartureSlot.of(
                request.departureTime() != null ? request.departureTime() : LocalDateTime.now());
        RouteCandidateFinder coordFinder = new RouteCandidateFinder(
                transferRule,
                graphRegistry.transferTimes(),
                graphRegistry.rentalIds(),
                stationInfos,
                graphRegistry::bikeStock);
        List<RouteSearchResponse> candidates = coordFinder.findCandidates(
                augmentedGraph, PLACE_ORIGIN_ID, PLACE_DEST_ID, MAX_CANDIDATES);
        List<RouteSearchResponse> withGeometry = withGeometryAll(candidates);
        List<RouteSearchResponse> ranked = RouteCandidateFinder.relabelByRank(
                RouteCandidateFinder.filterByModes(withGeometry, request.modes()));
        if (request.priority() == RoutePriority.COMFORT) {
            ranked = applyComfort(ranked, departureSlot);
        }
        return withRouteNames(ranked);
    }

    /**
     * 좌표 주변 보행 접근 가능한 역·정류장·대여소를 반경 {@value #ACCESS_RADIUS_M}m 안에서
     * 가까운 순으로 최대 {@value #MAX_ACCESS_CANDIDATES}개 찾아 임시 WALK 엣지로 만든다.
     * 실제 그래프에 연결돼 있지 않은 정점(좌표만 있고 고립된 경우)은 후보에서 뺀다 — 접근은
     * 됐는데 그 다음이 막힌 후보를 만들지 않기 위함이다.
     *
     * @param placeNodeId 이 좌표를 나타낼 임시 노드 ID
     * @param place 좌표
     * @param stationInfos 역·정류장·대여소 좌표 전체(그래프 레지스트리 원본)
     * @param graph 실제 연결 여부 확인용 그래프(임시 엣지 추가 전)
     * @param outgoing true면 좌표→후보 방향(출발지), false면 후보→좌표 방향(도착지)
     * @return 임시 WALK 엣지 목록. 반경 안 후보가 없으면 빈 목록
     */
    private List<Edge> accessEdges(
            String placeNodeId, RoutePlaceRequest place,
            Map<String, RouteMapper.StationInfo> stationInfos, RouteGraph graph, boolean outgoing) {
        record Candidate(String nodeId, double distanceM) {
        }
        List<Candidate> candidates = new ArrayList<>();
        for (RouteMapper.StationInfo info : stationInfos.values()) {
            if (info.lat() == null || info.lng() == null || !graph.containsNode(info.stationId())) {
                continue;
            }
            double distanceM = GeoDistance.haversineMeters(place.lat(), place.lng(), info.lat(), info.lng());
            if (distanceM > ACCESS_RADIUS_M) {
                continue;
            }
            candidates.add(new Candidate(info.stationId(), distanceM));
        }
        candidates.sort(Comparator.comparingDouble(Candidate::distanceM));

        List<Edge> edges = new ArrayList<>();
        for (Candidate candidate : candidates.subList(0, Math.min(MAX_ACCESS_CANDIDATES, candidates.size()))) {
            int sec = (int) Math.round(candidate.distanceM() / WalkEdgeBuilder.METERS_PER_SEC);
            edges.add(outgoing
                    ? new Edge(placeNodeId, candidate.nodeId(), WalkEdgeBuilder.WALK_ROUTE_ID, sec, 0, TravelMode.WALK)
                    : new Edge(candidate.nodeId(), placeNodeId, WalkEdgeBuilder.WALK_ROUTE_ID, sec, 0, TravelMode.WALK));
        }
        return edges;
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
}
