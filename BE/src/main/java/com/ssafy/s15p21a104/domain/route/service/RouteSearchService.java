package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.bus.entity.BusRoute;
import com.ssafy.s15p21a104.domain.bus.repository.BusRouteRepository;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionRepository;
import com.ssafy.s15p21a104.domain.congestion.scoring.CongestionScorer;
import com.ssafy.s15p21a104.domain.route.bike.BikeStockGate;
import com.ssafy.s15p21a104.domain.route.bike.geometry.BikeGeometryRegistry;
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
import com.ssafy.s15p21a104.domain.route.finder.CandidateModeSets;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.finder.ShortestPathFinder;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
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
        // 수단 조합별 하위 그래프는 그래프 로드 시점에 미리 계산해둔 캐시를 그대로 쓴다
        // (S15P21A104-155) — 요청마다 22만 엣지짜리 그래프를 7번씩 다시 필터링하지 않는다.
        List<RouteSearchResponse> candidates = algorithmCandidates(
                graphRegistry.candidateSubgraphs(), originStationId, destStationId, graphRegistry.stationInfos());
        // FE 175 지적사항: modes 필터는 routeType을 매긴 "뒤"에 걸리므로, 필터로 SHORTEST가
        // 빠지면 남은 후보 중 가장 빠른 게 ALTERNATIVE인 채로 나갈 수 있었다. 필터링 다음에
        // 다시 매겨 첫 번째가 항상 SHORTEST가 되도록 한다. routeName은 DB 조회가 필요해
        // 후보 수가 줄어든 다음(필터+재라벨링 이후)에 배치로 붙인다(FE-175 항목8).
        List<RouteSearchResponse> ranked = relabelByRank(filterByModes(candidates, modes));
        // priority=COMFORT가 아니면 순서·라벨을 전혀 건드리지 않는다(S15P21A104-157 AC2, 회귀 없음).
        if (priority == RoutePriority.COMFORT) {
            ranked = applyComfortPriority(ranked, departureSlot);
        }
        return withRouteNames(ranked);
    }

    /**
     * priority=COMFORT일 때 혼잡도가 가장 낮은 후보를 맨 앞으로 재정렬하고
     * {@link RouteType#LOW_CONGESTION}으로 표시한다(S15P21A104-157).
     *
     * <p>이미 나온 후보들을 재정렬만 할 뿐, 탐색 알고리즘·그래프는 건드리지 않는다.
     * 혼잡도 데이터가 하나도 없으면(노선 정보 자체가 없거나 congestion 테이블에 값이 없으면)
     * 아무것도 바꾸지 않는다 — 혼잡도를 반영한 척하지 않는다(값을 지어내지 않는다는 원칙).
     */
    private List<RouteSearchResponse> applyComfortPriority(
            List<RouteSearchResponse> candidates, DepartureSlot departureSlot) {
        Set<String> subwayRouteIds = new HashSet<>();
        for (RouteSearchResponse candidate : candidates) {
            for (RouteLegResponse leg : candidate.legs()) {
                if (leg.mode() == TravelMode.SUBWAY && leg.routeId() != null) {
                    subwayRouteIds.add(leg.routeId());
                }
            }
        }
        if (subwayRouteIds.isEmpty()) {
            return candidates;
        }
        Map<String, Double> levelByRouteId = new HashMap<>();
        for (String routeId : subwayRouteIds) {
            congestionRepository.findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                            CongestionTarget.LINE, routeId, departureSlot.dowType(), departureSlot.timeSlot())
                    .ifPresent(c -> levelByRouteId.put(routeId, c.getLevel().doubleValue()));
        }
        if (levelByRouteId.isEmpty()) {
            return candidates;
        }

        Map<RouteSearchResponse, Double> scoreByCandidate = new HashMap<>();
        for (RouteSearchResponse candidate : candidates) {
            CongestionScorer.score(candidate.legs(), levelByRouteId)
                    .ifPresent(score -> scoreByCandidate.put(candidate, score));
        }
        if (scoreByCandidate.isEmpty()) {
            return candidates;
        }

        List<RouteSearchResponse> sorted = new ArrayList<>(candidates);
        sorted.sort(Comparator.comparingDouble(
                candidate -> scoreByCandidate.getOrDefault(candidate, Double.MAX_VALUE)));

        List<RouteSearchResponse> relabeled = new ArrayList<>();
        boolean lowestTagged = false;
        for (RouteSearchResponse candidate : sorted) {
            if (!lowestTagged && scoreByCandidate.containsKey(candidate)) {
                relabeled.add(new RouteSearchResponse(
                        RouteType.LOW_CONGESTION, candidate.totalMinutes(), candidate.legs(),
                        candidate.source(), candidate.totalDistanceMeters(), candidate.transferCount()));
                lowestTagged = true;
            } else {
                relabeled.add(candidate);
            }
        }
        return relabeled;
    }

    /**
     * 허용 수단 조합별로 반복 탐색해 여러 경로 후보를 모은다(S15P21A104-185).
     *
     * <p>같은 최단경로 알고리즘을 하위 그래프 개수만큼 반복 적용할 뿐, 알고리즘 자체는
     * 그대로다. 하위 그래프는 {@link CandidateModeSets#CORE_MODE_SETS} 조합별로 미리
     * 필터링해둔 것을 받는다 — 역 검색은 {@link RouteGraphRegistry#candidateSubgraphs()}의
     * 캐시를 그대로 넘기고, 좌표 검색은 그 캐시에 접근 임시 엣지만 얹은 걸 넘긴다
     * (S15P21A104-155, 요청마다 22만 엣지짜리 그래프를 7번 다시 필터링하던 병목 제거).
     * 조합마다 나온 후보 중 leg 구성이 같은 것은 중복 제거하고, 소요시간이 가장 짧은
     * 것부터 정렬해 최대 {@value #MAX_CANDIDATES}개까지만 담는다. routeType 배정
     * ({@link RouteType#SHORTEST}/{@link RouteType#ALTERNATIVE})은 여기서 하지 않는다 —
     * {@code modes} 필터가 아직 안 걸린 시점이라 "가장 빠른 것"이 필터 후에도 그대로
     * 유지된다는 보장이 없다({@link #relabelByRank} 참고).
     */
    private List<RouteSearchResponse> algorithmCandidates(
            List<RouteGraph> candidateSubgraphs, String originStationId, String destStationId,
            Map<String, RouteMapper.StationInfo> stationInfos) {
        // 그래프 슬롯 선택과 탑승 시 wait_sec 가산(96/104 후속, 전우석)이 붙으면 여기서 넘긴다.
        TransferRule rule = transferRule.withTable(graphRegistry.transferTimes());

        Map<String, RouteSearchResponse> byLegSignature = new LinkedHashMap<>();
        for (RouteGraph subgraph : candidateSubgraphs) {
            searchOne(subgraph, rule, originStationId, destStationId, stationInfos)
                    .ifPresent(candidate -> byLegSignature.putIfAbsent(legSignature(candidate), candidate));
        }

        return byLegSignature.values().stream()
                .sorted(Comparator.comparingDouble(RouteSearchResponse::totalMinutes))
                .limit(MAX_CANDIDATES)
                .map(this::withGeometry)
                .toList();
    }

    /**
     * 소요시간순으로 이미 정렬된 후보 목록의 첫 번째를 {@link RouteType#SHORTEST}로,
     * 나머지를 {@link RouteType#ALTERNATIVE}로 다시 매긴다. {@code modes} 필터 "다음"에
     * 호출해야 한다 — 필터로 원래 최단 후보가 빠져도 남은 것 중 첫 번째가 SHORTEST가 된다.
     *
     * <p>geometry·거리는 {@link #algorithmCandidates}에서 이미 붙어 있으므로 여기서 다시
     * 계산하지 않는다 — 다시 부르면 카카오 도보 API를 후보마다 한 번 더 호출하게 된다.
     */
    private List<RouteSearchResponse> relabelByRank(List<RouteSearchResponse> candidates) {
        List<RouteSearchResponse> ranked = new ArrayList<>();
        for (int i = 0; i < candidates.size(); i++) {
            RouteSearchResponse candidate = candidates.get(i);
            RouteType routeType = i == 0 ? RouteType.SHORTEST : RouteType.ALTERNATIVE;
            ranked.add(new RouteSearchResponse(
                    routeType, candidate.totalMinutes(), candidate.legs(), candidate.source(),
                    candidate.totalDistanceMeters(), candidate.transferCount()));
        }
        return ranked;
    }

    /** 하위 그래프 하나에 최단경로 알고리즘을 1회 적용한다. 경로 없음·재고 게이트 탈락이면 빈 값. */
    private Optional<RouteSearchResponse> searchOne(
            RouteGraph subgraph, TransferRule rule, String originStationId, String destStationId,
            Map<String, RouteMapper.StationInfo> stationInfos) {
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
                    stationInfos, RouteType.SHORTEST, RouteSource.ALGORITHM,
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
        List<RouteLegResponse> legs = withGeometry(response.legs());
        return new RouteSearchResponse(
                response.routeType(), response.totalMinutes(), legs, response.source(),
                totalDistanceOf(legs), response.transferCount());
    }

    /**
     * leg 목록 전체에 geometry를 붙인다. 연속된 BIKE leg(사이에 WALK·TRANSFER 없이 대여소
     * 경계로만 나뉜 구간, {@link RouteMapper} rentalSplit 참고)는 하나의 실제 이동으로 묶어
     * {@link #withBikeRunGeometry}로 처리한다 — leg마다 독립 호출하면 같은 대여소인데도
     * 카카오 자전거 API의 도로 스냅 진입·이탈점이 달라져 경계가 끊겨 보인다(S15P21A104-153).
     */
    private List<RouteLegResponse> withGeometry(List<RouteLegResponse> legs) {
        List<RouteLegResponse> result = new ArrayList<>();
        int i = 0;
        while (i < legs.size()) {
            if (legs.get(i).mode() != TravelMode.BIKE) {
                result.add(withGeometry(legs.get(i)));
                i++;
                continue;
            }
            int end = i;
            while (end + 1 < legs.size() && legs.get(end + 1).mode() == TravelMode.BIKE) {
                end++;
            }
            result.addAll(withBikeRunGeometry(legs.subList(i, end + 1)));
            i = end + 1;
        }
        return result;
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
        return withGeometry(leg, geometry.get());
    }

    /**
     * 연속 BIKE leg 묶음을 전체 구간(첫 leg 출발→마지막 leg 도착) 1회 조회로 처리한다
     * (S15P21A104-153). 조회 결과 좌표열을 이어붙인 뒤, 각 leg의 실제 도착 좌표에 가장 가까운
     * 지점을 경계로 잘라 나눈다 — 인접 leg가 같은 지점(좌표열의 같은 인덱스)을 공유하므로
     * 끊김이 생기지 않는다. 좌표열이 실제 도착점과 너무 동떨어져 순서를 신뢰할 수 없으면
     * (경계가 뒤로 가지 않으면) 원본을 그대로 두고 값을 지어내지 않는다.
     */
    private List<RouteLegResponse> withBikeRunGeometry(List<RouteLegResponse> run) {
        RouteLegResponse first = run.get(0);
        RouteLegResponse last = run.get(run.size() - 1);
        if (first.fromLat() == null || first.fromLng() == null
                || last.toLat() == null || last.toLng() == null) {
            return run;
        }
        Optional<MultiLineStringResponse> geometry = bikeGeometryRegistry.geometryFor(
                first.fromNodeId(), last.toNodeId(),
                first.fromLat(), first.fromLng(), last.toLat(), last.toLng());
        if (geometry.isEmpty()) {
            return run;
        }
        List<List<Double>> points = flatten(geometry.get());
        if (points.size() < run.size() + 1) {
            return run;
        }
        List<RouteLegResponse> result = new ArrayList<>();
        int cursor = 0;
        for (int k = 0; k < run.size(); k++) {
            RouteLegResponse leg = run.get(k);
            int endIdx = k == run.size() - 1
                    ? points.size() - 1
                    : nearestIndex(points, cursor, leg.toLat(), leg.toLng());
            if (endIdx <= cursor) {
                return run;
            }
            MultiLineStringResponse legGeometry =
                    MultiLineStringResponse.of(List.of(new ArrayList<>(points.subList(cursor, endIdx + 1))));
            result.add(withGeometry(leg, legGeometry));
            cursor = endIdx;
        }
        return result;
    }

    private RouteLegResponse withGeometry(RouteLegResponse leg, MultiLineStringResponse geometry) {
        return new RouteLegResponse(
                leg.mode(),
                leg.fromNodeId(), leg.fromNodeName(), leg.fromLat(), leg.fromLng(),
                leg.toNodeId(), leg.toNodeName(), leg.toLat(), leg.toLng(),
                leg.routeId(), leg.minutes(),
                geometry, "available",
                distanceOf(geometry), leg.routeName()
        );
    }

    /** MultiLineString의 모든 LineString 좌표를 순서대로 이어붙인다. */
    private List<List<Double>> flatten(MultiLineStringResponse geometry) {
        List<List<Double>> points = new ArrayList<>();
        for (List<List<Double>> line : geometry.coordinates()) {
            points.addAll(line);
        }
        return points;
    }

    /** {@code fromIdx} 이후 지점 중 목표 좌표에 가장 가까운 인덱스. 역행하지 않도록 이후 구간만 본다. */
    private int nearestIndex(List<List<Double>> points, int fromIdx, double targetLat, double targetLng) {
        int best = fromIdx;
        double bestDist = Double.MAX_VALUE;
        for (int idx = fromIdx; idx < points.size(); idx++) {
            List<Double> point = points.get(idx);
            double dist = GeoDistance.haversineMeters(point.get(1), point.get(0), targetLat, targetLng);
            if (dist < bestDist) {
                bestDist = dist;
                best = idx;
            }
        }
        return best;
    }

    /**
     * geometry 좌표를 따라 실제 이동 거리를 더한다(FE-175 항목8). geometry가 없으면(직선거리로
     * 대체하지 않고) 호출하지 않는다 — {@link #withGeometry(RouteLegResponse)}에서만 쓴다.
     */
    private double distanceOf(MultiLineStringResponse geometry) {
        double total = 0;
        for (List<List<Double>> line : geometry.coordinates()) {
            for (int i = 0; i + 1 < line.size(); i++) {
                List<Double> from = line.get(i);
                List<Double> to = line.get(i + 1);
                total += GeoDistance.haversineMeters(from.get(1), from.get(0), to.get(1), to.get(0));
            }
        }
        return total;
    }

    /** legs 전부가 distanceMeters를 확보한 경우에만 합을 낸다. 하나라도 없으면 null(FE-175 항목8). */
    private Double totalDistanceOf(List<RouteLegResponse> legs) {
        double sum = 0;
        for (RouteLegResponse leg : legs) {
            if (leg.distanceMeters() == null) {
                return null;
            }
            sum += leg.distanceMeters();
        }
        return sum;
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
        // 캐시된 조합별 하위 그래프(RouteGraphRegistry.candidateSubgraphs()) 각각에 접근
        // 임시 엣지만 얹는다 — 22만 엣지짜리 원본을 7번 다시 필터링하지 않는다(S15P21A104-155).
        // withExtraEdges 자체도 얕은 복사라 안 건드리는 노드는 복사하지 않는다.
        List<RouteGraph> augmentedSubgraphs = graphRegistry.candidateSubgraphs().stream()
                .map(subgraph -> subgraph.withExtraEdges(accessEdges))
                .toList();

        Map<String, RouteMapper.StationInfo> stationInfos = new HashMap<>(baseInfos);
        stationInfos.put(PLACE_ORIGIN_ID, new RouteMapper.StationInfo(
                PLACE_ORIGIN_ID, origin.name(), origin.lat(), origin.lng()));
        stationInfos.put(PLACE_DEST_ID, new RouteMapper.StationInfo(
                PLACE_DEST_ID, destination.name(), destination.lat(), destination.lng()));

        DepartureSlot departureSlot = DepartureSlot.of(
                request.departureTime() != null ? request.departureTime() : LocalDateTime.now());
        List<RouteSearchResponse> candidates = algorithmCandidates(
                augmentedSubgraphs, PLACE_ORIGIN_ID, PLACE_DEST_ID, stationInfos);
        List<RouteSearchResponse> ranked = relabelByRank(filterByModes(candidates, request.modes()));
        if (request.priority() == RoutePriority.COMFORT) {
            ranked = applyComfortPriority(ranked, departureSlot);
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
