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
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
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

    /**
     * 허용 수단 조합별 대체 후보 탐색에 쓰는 "핵심 수단" 집합들. WALK는 접근·연결용이라 모든 조합에
     * 항상 포함한다({@link #withWalk}). 최단경로 알고리즘({@link ShortestPathFinder})은 그대로 두고,
     * 이 조합 수만큼 하위 그래프({@link RouteGraph#filterByModes})를 만들어 반복 탐색한다 —
     * 반드시 "최단"일 필요는 없는, 수단이 다른 대안 경로를 얻는 게 목적이다.
     */
    private static final List<Set<TravelMode>> CANDIDATE_CORE_MODE_SETS = List.of(
            Set.of(TravelMode.SUBWAY, TravelMode.BUS, TravelMode.BIKE),
            Set.of(TravelMode.SUBWAY),
            Set.of(TravelMode.BUS),
            Set.of(TravelMode.BIKE),
            Set.of(TravelMode.SUBWAY, TravelMode.BUS),
            Set.of(TravelMode.SUBWAY, TravelMode.BIKE),
            Set.of(TravelMode.BUS, TravelMode.BIKE)
    );

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

    /**
     * 허용 수단 조합별로 반복 탐색해 여러 경로 후보를 모은다(S15P21A104-185).
     *
     * <p>같은 최단경로 알고리즘을 조합 수만큼 서로 다른 하위 그래프에 적용할 뿐,
     * 알고리즘 자체는 그대로다. 조합마다 나온 후보 중 leg 구성이 같은 것은 중복 제거하고,
     * 소요시간이 가장 짧은 것부터 정렬해 {@link RouteType#SHORTEST} 하나와 나머지
     * {@link RouteType#ALTERNATIVE}로 표시한 뒤 최대 {@value #MAX_CANDIDATES}개까지만 담는다.
     */
    private List<RouteSearchResponse> algorithmCandidates(
            RouteGraph graph, String originStationId, String destStationId, DepartureSlot departureSlot) {
        // departureSlot은 이번 커밋(API 파라미터, S15P21A104-63)에서는 아직 안 쓴다 — 그래프 슬롯 선택과
        // 탑승 시 wait_sec 가산(96/104 후속, 전우석)이 붙으면 graph()/ShortestPathFinder 호출에 넘긴다.
        TransferRule rule = transferRule.withTable(graphRegistry.transferTimes());

        Map<String, RouteSearchResponse> byLegSignature = new LinkedHashMap<>();
        for (Set<TravelMode> coreModes : CANDIDATE_CORE_MODE_SETS) {
            RouteGraph subgraph = graph.filterByModes(withWalk(coreModes));
            searchOne(subgraph, rule, originStationId, destStationId)
                    .ifPresent(candidate -> byLegSignature.putIfAbsent(legSignature(candidate), candidate));
        }

        List<RouteSearchResponse> sorted = byLegSignature.values().stream()
                .sorted(Comparator.comparingDouble(RouteSearchResponse::totalMinutes))
                .limit(MAX_CANDIDATES)
                .toList();

        List<RouteSearchResponse> ranked = new ArrayList<>();
        for (int i = 0; i < sorted.size(); i++) {
            RouteSearchResponse candidate = sorted.get(i);
            RouteType routeType = i == 0 ? RouteType.SHORTEST : RouteType.ALTERNATIVE;
            ranked.add(withGeometry(new RouteSearchResponse(
                    routeType, candidate.totalMinutes(), candidate.legs(), candidate.source())));
        }
        return ranked;
    }

    /** 하위 그래프 하나에 최단경로 알고리즘을 1회 적용한다. 경로 없음·재고 게이트 탈락이면 빈 값. */
    private Optional<RouteSearchResponse> searchOne(
            RouteGraph subgraph, TransferRule rule, String originStationId, String destStationId) {
        try {
            FoundPath found = new ShortestPathFinder(rule).find(subgraph, originStationId, destStationId);
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
            // routeType은 여기서 임의로 SHORTEST를 넣어두고, 전체 후보를 모은 뒤(algorithmCandidates)
            // 소요시간 기준으로 다시 매긴다 — 이 시점엔 다른 후보와 비교할 수 없다.
            Optional<RouteSearchResponse> response = RouteMapper.toResponseWithTransfers(
                    new RouteMapper.EnginePath(segments, found.totalSec(), found.transferCount()),
                    graphRegistry.stationInfos(), RouteType.SHORTEST, RouteSource.ALGORITHM,
                    transferSecs, graphRegistry.rentalIds());
            return response.filter(r -> BikeStockGate.passesEdges(
                    found.edges().stream().map(Edge::fromNode).toList(),
                    found.edges().stream().map(Edge::mode).toList(),
                    graphRegistry.bikeStock()));
        } catch (DomainException exception) {
            if (exception.getErrorType() == ErrorType.ROUTE_NOT_FOUND
                    || exception.getErrorType() == ErrorType.STATION_NOT_FOUND) {
                // 이 수단 조합으로는 출발·도착이 아예 연결되지 않거나 하위 그래프에 없는 역이다.
                // 후보 하나가 없을 뿐이므로 건너뛴다(전체 탐색을 실패시키지 않는다).
                return Optional.empty();
            }
            throw exception;
        }
    }

    /** WALK는 접근·연결용이라 모든 수단 조합에 항상 포함한다. */
    private Set<TravelMode> withWalk(Set<TravelMode> coreModes) {
        Set<TravelMode> modes = new HashSet<>(coreModes);
        modes.add(TravelMode.WALK);
        return modes;
    }

    /** leg의 (수단·출발·도착·노선) 순서로 만든 서명. 같으면 사실상 같은 경로로 보고 중복 제거한다. */
    private String legSignature(RouteSearchResponse response) {
        StringBuilder signature = new StringBuilder();
        for (RouteLegResponse leg : response.legs()) {
            signature.append(leg.mode()).append(':')
                    .append(leg.fromNodeId()).append("->").append(leg.toNodeId()).append(':')
                    .append(leg.routeId()).append('|');
        }
        return signature.toString();
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
