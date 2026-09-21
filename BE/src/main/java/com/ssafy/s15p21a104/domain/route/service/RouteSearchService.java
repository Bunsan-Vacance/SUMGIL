package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.bus.entity.BusRoute;
import com.ssafy.s15p21a104.domain.bus.repository.BusRouteRepository;
import com.ssafy.s15p21a104.domain.buscongestion.BusArrival;
import com.ssafy.s15p21a104.domain.buscongestion.BusCongestionProperties;
import com.ssafy.s15p21a104.domain.buscongestion.BusCongestionReader;
import com.ssafy.s15p21a104.domain.buscongestion.BusCongestionWindow;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionPredRepository;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionRepository;
import com.ssafy.s15p21a104.domain.congestion.scoring.CongestionScorer;
import com.ssafy.s15p21a104.domain.congestion.scoring.LinkCongestionScorer;
import com.ssafy.s15p21a104.domain.congestion.scoring.SubwayDirectionResolver;
import com.ssafy.s15p21a104.domain.route.bike.geometry.BikeGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.dto.request.CoordinateRouteSearchRequest;
import com.ssafy.s15p21a104.domain.route.dto.request.DepartureSlot;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePlaceRequest;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePriority;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.CongestionPrediction;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.finder.ScoredCandidate;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RouteGeometryEnhancer;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.LegContract;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.route.scoring.CongestionCostModel;
import com.ssafy.s15p21a104.domain.route.scoring.CongestionPredictionResolver;
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
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Function;

/**
 * 경로 검색. 그래프 미적재 시 빈 배열(경로 없음)로 응답한다. 가짜 후보를 만들지 않는다.
 */
@Service
// 생성자가 둘이라(아래 10인자 편의 생성자) Spring 이 어느 쪽을 쓸지 스스로 못 고른다 —
// Lombok 이 만드는 전체 생성자에 @Autowired 를 붙여 주입 대상을 명시한다.
// 없으면 기동 때 "No default constructor found" 로 죽는다(단위 테스트로는 안 잡힌다).
@RequiredArgsConstructor(onConstructor_ = @Autowired)
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
    private final CongestionPredRepository congestionPredRepository;
    private final BusCongestionReader busCongestionReader;
    private final BusCongestionProperties busCongestionProperties;
    private final Clock clock;

    /**
     * 버스 실시간 혼잡도(297) 없이 만드는 기존 형태. 혼잡도는 응답에 등급만 얹는 곁가지라 탐색
     * 동작을 검증하는 테스트가 이 의존을 몰라도 되게 남겨 둔다 — 이 경로에서는 항상 null 등급이다.
     */
    public RouteSearchService(
            StationRepository stationRepository,
            RouteGraphRegistry graphRegistry,
            TransferRule transferRule,
            RailGeometryRegistry railGeometryRegistry,
            WalkGeometryRegistry walkGeometryRegistry,
            BikeGeometryRegistry bikeGeometryRegistry,
            RouteLineRepository routeLineRepository,
            BusRouteRepository busRouteRepository,
            CongestionRepository congestionRepository,
            CongestionPredRepository congestionPredRepository) {
        this(stationRepository, graphRegistry, transferRule, railGeometryRegistry, walkGeometryRegistry,
                bikeGeometryRegistry, routeLineRepository, busRouteRepository, congestionRepository,
                congestionPredRepository,
                BusCongestionReader.disabled(),
                new BusCongestionProperties(false, null, 0, null, null, null, null),
                Clock.systemDefaultZone());
    }

    /** 6경로 응답 상한: 속도 3 + 혼잡 3(S15P21A104-214, 배포 문서 순서표). */
    private static final int SPEED_ROUTES = 3;

    /** 6경로 응답 상한: 속도 3 + 혼잡 3(S15P21A104-214, 배포 문서 순서표). */
    private static final int CALM_ROUTES = 3;

    /** 혼잡 가중치 λ (S15P21A104-216, 기본 0.5). transfer.default-sec 노브와 같은 패턴. */
    @Value("${route.congestion-lambda:0.5}")
    private double congestionLambda;

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
        // 생략 시 현재 시각 기준. 슬롯은 탐색 그래프 선택에도 쓴다(190).
        LocalDateTime effectiveDepartureTime = departureTime != null ? departureTime : LocalDateTime.now();
        DepartureSlot departureSlot = DepartureSlot.of(effectiveDepartureTime);
        RouteGraph slotGraph = graphRegistry.graphFor(departureSlot.dowType(), departureSlot.timeSlot());
        if (slotGraph == null) {
            throw new DomainException(ErrorType.ROUTE_DATA_NOT_READY);
        }
        // 214·216: 속도 3(시간 탐색) + 혼잡 3(혼잡 가중 탐색). modes 필터는 라벨 전에 건다.
        SixResult assembled = sixRoutes(
                candidateFinder(), slotGraph, originStationId, destStationId, modes,
                effectiveDepartureTime);
        // geometry·routeName은 후보 확정 후(6개 이하)에 배치로 붙인다(FE-175 항목8).
        // 출발시각을 넘겨 live window일 때만 BUS 실시간 등급을 prefetch한다(297).
        List<RouteSearchResponse> named =
                withRouteNames(withGeometryAll(assembled.six()), effectiveDepartureTime);
        // 계약 필드(236)는 맨 마지막에 붙인다 — geometry·이름 단계는 필드를 그대로 둔다.
        return withContractFields(named, assembled, effectiveDepartureTime);
    }

    /** 탐색 결과 묶음 — 최종 6건과 점수 계산에 쓴 원본 후보. */
    private record SixResult(List<RouteSearchResponse> six,
                             List<ScoredCandidate> timeScored,
                             List<ScoredCandidate> calmScored) {
    }

    /**
     * 시간 탐색 1회 + 혼잡 가중 탐색 1회로 속도 3 + 혼잡 3을 뽑는다(S15P21A104-216).
     * 역 검색·좌표 검색이 같은 파이프를 쓴다.
     */
    private SixResult sixRoutes(RouteCandidateFinder finder, RouteGraph graph,
            String originStationId, String destStationId, List<TravelMode> modes,
            LocalDateTime departureTime) {
        DepartureSlot slot = DepartureSlot.of(departureTime);
        List<ScoredCandidate> timeScored = RouteCandidateFinder.filterScoredByModes(
                finder.findCandidatesWithPaths(
                        graph, originStationId, destStationId, MAX_CANDIDATES, modes),
                modes);
        List<ScoredCandidate> calmScored;
        try {
            calmScored = RouteCandidateFinder.filterScoredByModes(
                    finder.findCandidatesWithPaths(graph, originStationId, destStationId,
                            MAX_CANDIDATES, modes,
                            CongestionCostModel.of(congestionLambda,
                                    congestionLevels(slot.dowType(), slot.timeSlot()),
                                    graphRegistry.busRouteIndex())),
                    modes);
        } catch (RuntimeException e) {
            calmScored = List.of();
        }
        List<RouteSearchResponse> filtered =
                timeScored.stream().map(ScoredCandidate::response).toList();
        List<RouteSearchResponse> ranked = RouteCandidateFinder.relabelByRank(filtered);
        List<RouteSearchResponse> speed = ranked.stream()
                .limit(SPEED_ROUTES)
                .toList();
        // 158(통지 05 S-1): 링크 단위·통과 시각 슬롯으로 정제. 혼잡 탐색이 비면 시간 후보에서 고른다.
        List<RouteSearchResponse> calm = scoreRanker().topCalmByLink(
                calmScored.isEmpty() ? timeScored : calmScored,
                departureTime, congestionPredLookup(), CALM_ROUTES);
        // 부족분 채움 풀은 두 탐색 합본(시간순).
        List<RouteSearchResponse> pool = new ArrayList<>(ranked);
        for (ScoredCandidate calmCandidate : calmScored) {
            pool.add(calmCandidate.response());
        }
        pool.sort(Comparator.comparingDouble(RouteSearchResponse::totalMinutes));
        // 완전 중복(속도∩혼잡)·유사경로(탄 것만 비교) 제거 후 부족분은 전체 후보에서 채운다.
        List<RouteSearchResponse> six = RouteCandidateFinder.diversify(
                speed, calm, pool, SPEED_ROUTES + CALM_ROUTES);
        return new SixResult(six, timeScored, calmScored);
    }

    /**
     * 계약 필드 부착(S15P21A104-236 혼잡 예측 · 237 구간 구분은 legs 변환 포함).
     * 최종 후보(6개 이하)에만 계산한다 — 조회는 PK 단건이라 상한이 걸린다.
     */
    private List<RouteSearchResponse> withContractFields(List<RouteSearchResponse> six,
            SixResult assembled, LocalDateTime departureTime) {
        DepartureSlot slot = DepartureSlot.of(departureTime);
        Map<String, List<Edge>> edgesBySignature = new HashMap<>();
        for (ScoredCandidate scored : assembled.timeScored()) {
            edgesBySignature.putIfAbsent(
                    RouteCandidateFinder.exactSignature(scored.response()), scored.path().edges());
        }
        for (ScoredCandidate scored : assembled.calmScored()) {
            edgesBySignature.putIfAbsent(
                    RouteCandidateFinder.exactSignature(scored.response()), scored.path().edges());
        }
        // stat 폴백용 LINE 레벨 — 최종 후보의 SUBWAY 노선만 묶어 조회한다.
        Set<String> subwayRouteIds = new HashSet<>();
        for (RouteSearchResponse response : six) {
            for (RouteLegResponse leg : response.legs()) {
                if (leg.mode() == TravelMode.SUBWAY && leg.routeId() != null) {
                    subwayRouteIds.add(leg.routeId());
                }
            }
        }
        Map<String, Double> levelByRouteId = new HashMap<>();
        CongestionCostModel.LevelSource levels =
                congestionLevels(slot.dowType(), slot.timeSlot());
        for (String routeId : subwayRouteIds) {
            Double level = levels.levelOf("LINE", routeId);
            if (level != null) {
                levelByRouteId.put(routeId, level);
            }
        }
        LocalDate today = LocalDate.now(ZoneId.of("Asia/Seoul"));
        List<RouteSearchResponse> out = new ArrayList<>();
        for (RouteSearchResponse response : six) {
            List<RouteLegResponse> legs = LegContract.withContractFields(
                    response.legs(), graphRegistry.rentalIds());
            List<Edge> edges = edgesBySignature.getOrDefault(
                    RouteCandidateFinder.exactSignature(response), List.of());
            AtomicBoolean truncated = new AtomicBoolean(false);
            Optional<Double> linkScore = edges.isEmpty() ? Optional.empty()
                    : LinkCongestionScorer.score(
                                    edges, departureTime, congestionPredLookup(truncated))
                            .map(LinkCongestionScorer.Result::weightedAverage);
            Optional<Double> lineScore =
                    CongestionScorer.score(legs, levelByRouteId);
            CongestionPrediction prediction = CongestionPredictionResolver.resolve(
                    linkScore, lineScore, truncated.get(),
                    departureTime.toLocalDate(), today);
            out.add(new RouteSearchResponse(response.routeType(), response.totalMinutes(),
                    legs, response.source(), response.totalDistanceMeters(),
                    response.transferCount(), prediction));
        }
        return out;
    }

    /** 슬롯 고정 혼잡도 조회 — 탐색 비용 모델에 넘긴다(216). */
    private CongestionCostModel.LevelSource congestionLevels(int dowType, int timeSlot) {
        return (targetType, targetId) -> {
            CongestionTarget target = "LINE".equals(targetType) ? CongestionTarget.LINE
                    : "ROUTE".equals(targetType) ? CongestionTarget.ROUTE : null;
            if (target == null || targetId == null) {
                return null;
            }
            return congestionRepository
                    .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                            target, targetId, dowType, timeSlot)
                    .map(c -> c.getLevel().doubleValue())
                    .orElse(null);
        };
    }

    /** 탐색→매핑 조립기. 레지스트리 값을 주입해 만든다. */
    private RouteCandidateFinder candidateFinder() {
        return new RouteCandidateFinder(
                transferRule,
                graphRegistry.transferTimes(),
                graphRegistry.rentalIds(),
                graphRegistry.stationInfos(),
                graphRegistry::bikeStock,
                graphRegistry.busRouteIndex());
    }

    /** 쾌적 순위기. 혼잡도 조회 함수를 주입해 만든다. */
    private RouteScoreRanker scoreRanker() {
        return new RouteScoreRanker(
                (targetType, targetId, dowType, timeSlot) -> congestionRepository
                        .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                                CongestionTarget.LINE, targetId, dowType, timeSlot)
                        .map(c -> c.getLevel().doubleValue())
                        .orElse(null));
    }

    /**
     * 링크 단위 혼잡도 예측 조회 함수(S15P21A104-158, 통지 05 S-1). 방향을 모르면
     * (2호선 지선 등, {@link SubwayDirectionResolver} 참고) 조회 자체를 안 하고 null —
     * 결측과 동일하게 다룬다.
     */
    private LinkCongestionScorer.LinkLevelLookup congestionPredLookup() {
        return congestionPredLookup(new AtomicBoolean());
    }

    /**
     * 방향 미판정을 기록하는 판(S15P21A104-236 LINE1_TRUNCATED).
     *
     * @param directionUnresolved SUBWAY 엣지의 방향을 못 정할 때 true로 세운다
     */
    private LinkCongestionScorer.LinkLevelLookup congestionPredLookup(
            AtomicBoolean directionUnresolved) {
        return (edge, passThroughTime) -> {
            var direction =
                    SubwayDirectionResolver.resolve(edge.fromNode(), edge.toNode(), edge.routeId());
            if (direction.isEmpty()) {
                if (edge.mode() == TravelMode.SUBWAY) {
                    directionUnresolved.set(true);
                }
                return null;
            }
            return direction
                    .flatMap(resolved -> congestionPredRepository
                            .findById_PredDateAndId_FromStationIdAndId_ToStationIdAndId_LineIdAndId_DirectionAndId_TimeSlot(
                                    passThroughTime.toLocalDate(), edge.fromNode(), edge.toNode(),
                                    edge.routeId(), resolved,
                                    DepartureSlot.of(passThroughTime).timeSlot())
                            .map(com.ssafy.s15p21a104.domain.congestion.entity.CongestionPred::getLevel))
                    .map(java.math.BigDecimal::doubleValue)
                    .orElse(null);
        };
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
     * 사람이 읽는 노선 이름을 배치로 붙인다(213 T4). {@link RouteNameResolver}에
     * 위임하고 서비스는 DB 조회 함수만 넘긴다.
     *
     * <p>버스 실시간 혼잡도(297)도 여기서 붙는다. <b>지금 출발 검색이고 버스 구간이 있을 때만</b>
     * 그 승차 정류소를 한 번에 받아 온다 — 지하철만 나온 검색은 외부 호출이 아예 없다.
     *
     * @param departureTime 요청한 출발 시각(없으면 null = 지금). 실시간 값을 붙일지 가른다
     */
    private List<RouteSearchResponse> withRouteNames(
            List<RouteSearchResponse> responses, LocalDateTime departureTime) {
        Function<String, Map<String, BusArrival>> congestion = stopId -> Map.of();
        if (BusCongestionWindow.isLive(departureTime, clock, busCongestionProperties.nowWindow())) {
            Set<String> stops = RouteNameResolver.busBoardingStops(responses);
            if (!stops.isEmpty()) {
                busCongestionReader.prefetch(stops);
                congestion = busCongestionReader::forStop;
            }
        }
        return withRouteNames(responses, congestion);
    }

    private List<RouteSearchResponse> withRouteNames(
            List<RouteSearchResponse> responses, Function<String, Map<String, BusArrival>> busCongestion) {
        return new RouteNameResolver(
                ids -> {
                    Map<String, String> names = new HashMap<>();
                    for (Line line : routeLineRepository.findAllById(ids)) {
                        names.put(line.getLineId(), line.getName());
                    }
                    return names;
                },
                ids -> {
                    Map<String, String> names = new HashMap<>();
                    for (BusRoute busRoute : busRouteRepository.findAllById(ids)) {
                        names.put(busRoute.getRouteId(), busRoute.getName());
                    }
                    return names;
                },
                graphRegistry.busRouteIndex(),
                ids -> {
                    Map<String, Integer> headways = new HashMap<>();
                    for (BusRoute busRoute : busRouteRepository.findAllById(ids)) {
                        headways.put(busRoute.getRouteId(), busRoute.getHeadwayMin());
                    }
                    return headways;
                },
                busCongestion).withRouteNames(responses);
    }

    /** 좌표 검색 전용 임시 노드 ID(S15P21A104-187). 요청 하나 안에서만 쓰고 그래프에 남기지 않는다. */
    private static final String PLACE_ORIGIN_ID = "PLACE-ORIGIN";

    private static final String PLACE_DEST_ID = "PLACE-DEST";

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

        DepartureSlot coordSlot = DepartureSlot.of(
                request.departureTime() != null ? request.departureTime() : LocalDateTime.now());
        RouteGraph slotGraph = graphRegistry.graphFor(coordSlot.dowType(), coordSlot.timeSlot());
        if (slotGraph == null) {
            throw new DomainException(ErrorType.ROUTE_DATA_NOT_READY);
        }

        Map<String, RouteMapper.StationInfo> baseInfos = graphRegistry.stationInfos();
        List<Edge> originAccessEdges = CoordinateAccessEdges.accessEdges(
                PLACE_ORIGIN_ID, origin.lat(), origin.lng(), baseInfos, slotGraph, true,
                graphRegistry.stationIds());
        List<Edge> destAccessEdges = CoordinateAccessEdges.accessEdges(
                PLACE_DEST_ID, destination.lat(), destination.lng(), baseInfos, slotGraph, false,
                graphRegistry.stationIds());
        if (originAccessEdges.isEmpty() || destAccessEdges.isEmpty()) {
            throw new DomainException(ErrorType.ACCESS_CANDIDATE_NOT_FOUND);
        }

        List<Edge> accessEdges = new ArrayList<>(originAccessEdges);
        accessEdges.addAll(destAccessEdges);
        // 슬롯 그래프에 접근 임시 엣지만 얹는다 (190: 슬롯 반영 + 213 T2 1회 탐색).
        // withExtraEdges 자체도 얕은 복사라 안 건드리는 노드는 복사하지 않는다.
        RouteGraph augmentedGraph = slotGraph.withExtraEdges(accessEdges);

        Map<String, RouteMapper.StationInfo> stationInfos = new HashMap<>(baseInfos);
        stationInfos.put(PLACE_ORIGIN_ID, new RouteMapper.StationInfo(
                PLACE_ORIGIN_ID, origin.name(), origin.lat(), origin.lng()));
        stationInfos.put(PLACE_DEST_ID, new RouteMapper.StationInfo(
                PLACE_DEST_ID, destination.name(), destination.lat(), destination.lng()));

        RouteCandidateFinder coordFinder = new RouteCandidateFinder(
                transferRule,
                graphRegistry.transferTimes(),
                graphRegistry.rentalIds(),
                stationInfos,
                graphRegistry::bikeStock,
                graphRegistry.busRouteIndex());
        // 214·216: 역 검색과 같은 6경로 파이프 (속도 3 + 혼잡 3).
        LocalDateTime coordDeparture =
                request.departureTime() != null ? request.departureTime() : LocalDateTime.now();
        SixResult coordAssembled = sixRoutes(coordFinder, augmentedGraph,
                PLACE_ORIGIN_ID, PLACE_DEST_ID, request.modes(), coordDeparture);
        List<RouteSearchResponse> coordNamed =
                withRouteNames(withGeometryAll(coordAssembled.six()), coordDeparture);
        return withContractFields(coordNamed, coordAssembled, coordDeparture);
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
