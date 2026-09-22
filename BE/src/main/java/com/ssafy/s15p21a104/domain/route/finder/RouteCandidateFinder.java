package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.bike.BikeStockGate;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Supplier;
import java.util.function.ToLongFunction;

/**
 * 탐색→매핑 후보 조립(S15P21A104-213 T4).
 *
 * <p>{@code RouteSearchService}에서 분리했다. 원본 그래프 1회 + K-path로 서로 다른
 * leg 서명의 후보를 시간순으로 뽑고, 응답 DTO로 바꾼다. routeType 배정은 하지 않는다 —
 * {@code modes} 필터가 아직 안 걸린 시점이라 "가장 빠른 것"이 필터 후에도 그대로
 * 유지된다는 보장이 없다({@link #relabelByRank} 참고).
 *
 * <p>재고 게이트·환승 실측·대여소 집합은 생성자로 주입한다. DB에 직접 의존하지 않는다.
 */
public final class RouteCandidateFinder {

    private final TransferRule transferRule;
    private final Map<TransferRule.TransferKey, Integer> transferTimes;
    private final Set<String> rentalIds;
    private final Map<String, RouteMapper.StationInfo> stationInfos;
    private final Supplier<Map<String, Integer>> bikeStock;
    private final BusRouteIndex busRouteIndex;
    private final RaptorInput raptorInput;

    /** RAPTOR 탐색 입력(S15P21A104-217 ③). null이면 레거시 엔진만 쓴다. */
    public record RaptorInput(com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorRouteSet routeSet,
                              List<Edge> accessEdges) {
    }

    /** 라운드 상한 — 환승 3회 내외(4라운드) */
    static final int RAPTOR_MAX_ROUNDS = 4;

    /** K 후보를 위한 세그먼트 금지 재스캔 상한 — 스캔 1회가 ms 단위라 넉넉히 둔다. */
    static final int RAPTOR_MAX_BAN_RUNS = 8;

    /**
     * @param transferRule 환승 비용 규칙
     * @param transferTimes 환승 실측표
     * @param rentalIds 대여소 ID 집합
     * @param stationInfos 역 표시 정보
     * @param bikeStock 대여소별 예상 재고 공급자
     * @param busRouteIndex 정규 BUS 구간 운행 노선 인덱스(234). null이면 routeId 폴백
     * @param raptorInput RAPTOR 입력(217). null이면 레거시만
     */
    public RouteCandidateFinder(
            TransferRule transferRule,
            Map<TransferRule.TransferKey, Integer> transferTimes,
            Set<String> rentalIds,
            Map<String, RouteMapper.StationInfo> stationInfos,
            Supplier<Map<String, Integer>> bikeStock,
            BusRouteIndex busRouteIndex,
            RaptorInput raptorInput) {
        this.transferRule = transferRule;
        this.transferTimes = transferTimes;
        this.rentalIds = rentalIds;
        this.stationInfos = stationInfos;
        this.bikeStock = bikeStock;
        this.busRouteIndex = busRouteIndex;
        this.raptorInput = raptorInput;
    }

    /**
     * @param transferRule 환승 비용 규칙
     * @param transferTimes 환승 실측표
     * @param rentalIds 대여소 ID 집합
     * @param stationInfos 역 표시 정보
     * @param bikeStock 대여소별 예상 재고 공급자
     * @param busRouteIndex 정규 BUS 구간 운행 노선 인덱스(234). null이면 routeId 폴백
     */
    public RouteCandidateFinder(
            TransferRule transferRule,
            Map<TransferRule.TransferKey, Integer> transferTimes,
            Set<String> rentalIds,
            Map<String, RouteMapper.StationInfo> stationInfos,
            Supplier<Map<String, Integer>> bikeStock,
            BusRouteIndex busRouteIndex) {
        this(transferRule, transferTimes, rentalIds, stationInfos, bikeStock, busRouteIndex, null);
    }

    /**
     * @param transferRule 환승 비용 규칙
     * @param transferTimes 환승 실측표
     * @param rentalIds 대여소 ID 집합
     * @param stationInfos 역 표시 정보
     * @param bikeStock 대여소별 예상 재고 공급자
     */
    public RouteCandidateFinder(
            TransferRule transferRule,
            Map<TransferRule.TransferKey, Integer> transferTimes,
            Set<String> rentalIds,
            Map<String, RouteMapper.StationInfo> stationInfos,
            Supplier<Map<String, Integer>> bikeStock) {
        this(transferRule, transferTimes, rentalIds, stationInfos, bikeStock, null);
    }

    /**
     * @param transferRule 환승 비용 규칙
     * @param transferTimes 환승 실측표
     * @param rentalIds 대여소 ID 집합
     * @param stationInfos 역 표시 정보
     */
    public RouteCandidateFinder(
            TransferRule transferRule,
            Map<TransferRule.TransferKey, Integer> transferTimes,
            Set<String> rentalIds,
            Map<String, RouteMapper.StationInfo> stationInfos) {
        this(transferRule, transferTimes, rentalIds, stationInfos, Map::of);
    }

    /**
     * 원본 그래프 1회에 K-path로 여러 경로 후보를 모은다.
     *
     * @param graph 원본 그래프
     * @param originStationId 출발역 ID
     * @param destStationId 도착역 ID
     * @param maxCandidates 최대 후보 수
     * @return 소요시간 오름차순 후보 (routeType 미지정)
     */
    public List<RouteSearchResponse> findCandidates(
            RouteGraph graph, String originStationId, String destStationId, int maxCandidates) {
        return findCandidates(graph, originStationId, destStationId, maxCandidates, null);
    }

    /**
     * 허용 수단을 탐색 안에서 거르는 판(S15P21A104-215 §3.4).
     *
     * @param allowedModes 허용 수단. null·빈 목록이면 전체
     */
    public List<RouteSearchResponse> findCandidates(
            RouteGraph graph, String originStationId, String destStationId, int maxCandidates,
            List<TravelMode> allowedModes) {
        return findCandidatesWithPaths(graph, originStationId, destStationId, maxCandidates, allowedModes)
                .stream()
                .map(ScoredCandidate::response)
                .toList();
    }

    /**
     * {@link #findCandidates}와 같은 후보를, 링크 단위 혼잡도 스코어링(S-1)이 쓸 수 있게
     * 원본 {@link FoundPath}와 같이 돌려준다(S15P21A104-158).
     */
    public List<ScoredCandidate> findCandidatesWithPaths(
            RouteGraph graph, String originStationId, String destStationId, int maxCandidates) {
        return findCandidatesWithPaths(graph, originStationId, destStationId, maxCandidates, null);
    }

    /**
     * 허용 수단을 탐색 안에서 거르는 판(S15P21A104-215 §3.4).
     *
     * @param allowedModes 허용 수단. null·빈 목록이면 전체
     */
    public List<ScoredCandidate> findCandidatesWithPaths(
            RouteGraph graph, String originStationId, String destStationId, int maxCandidates,
            List<TravelMode> allowedModes) {
        return findCandidatesWithPaths(graph, originStationId, destStationId, maxCandidates,
                allowedModes, null);
    }

    /**
     * 엣지 비용 모델까지 받는 판(S15P21A104-216 혼잡 가중 탐색).
     *
     * @param allowedModes 허용 수단. null·빈 목록이면 전체
     * @param costModel 엣지 이동 비용. null이면 시간 비용
     */
    public List<ScoredCandidate> findCandidatesWithPaths(
            RouteGraph graph, String originStationId, String destStationId, int maxCandidates,
            List<TravelMode> allowedModes, KShortestPathFinder.EdgeCostModel costModel) {
        TransferRule rule = transferRule.withTable(transferTimes);
        // RAPTOR 우선(217) — 빈 결과면 레거시로 폴백해 "탐색은 항상 성공" 원칙을 지킨다.
        List<FoundPath> paths = List.of();
        if (raptorInput != null && raptorInput.routeSet() != null) {
            paths = findWithRaptor(raptorInput, originStationId, destStationId, maxCandidates,
                    allowedModes, costModel);
        }
        if (paths.isEmpty()) {
            paths = findWithLegacy(graph, originStationId, destStationId, maxCandidates,
                    allowedModes, costModel, rule);
        }

        Map<String, ScoredCandidate> byLegSignature = new LinkedHashMap<>();
        for (FoundPath found : paths) {
            toCandidate(found, rule)
                    .ifPresent(candidate -> byLegSignature.putIfAbsent(
                            legSignature(candidate), new ScoredCandidate(candidate, found)));
        }

        return byLegSignature.values().stream()
                .sorted(Comparator.comparingDouble(sc -> sc.response().totalMinutes()))
                .limit(maxCandidates)
                .toList();
    }

    /** 레거시(K 라벨링 다익스트라) 탐색 — RAPTOR 미적용·실패 시 폴백(215·216 경로 그대로). */
    private List<FoundPath> findWithLegacy(RouteGraph graph, String originStationId,
            String destStationId, int maxCandidates, List<TravelMode> allowedModes,
            KShortestPathFinder.EdgeCostModel costModel, TransferRule rule) {
        // 그래프 슬롯 선택과 탑승 시 wait_sec 가산(96/104 후속, 전우석)이 붙으면 여기서 넘긴다.
        ToLongFunction<String> lowerBound = remainingLowerBound(destStationId);
        List<FoundPath> paths = new KShortestPathFinder(rule, busRouteIndex)
                .findK(graph, originStationId, destStationId, maxCandidates, allowedModes,
                        lowerBound, costModel);
        if (paths.isEmpty() && allowsBus(allowedModes)) {
            // 탐색 작업 상한이 BUS 포함 탐색에서 목적지 후보를 만나기 전에 소진되면 빈 결과가 된다.
            // 같은 조건에서 BUS만 뺀 경로는 존재할 수 있다 — 수단을 추가했다고 기존 경로가
            // 사라지면 안 되므로(운영 빈 결과 회귀, 2026-09-20 보고) 비BUS로 제한 재탐색한다.
            paths = new KShortestPathFinder(rule, busRouteIndex)
                    .findK(graph, originStationId, destStationId, maxCandidates,
                            withoutBus(allowedModes), lowerBound, costModel);
        }
        return paths;
    }

    /** RAPTOR 노선 스캔 탐색 — journey를 FoundPath로 전개한다(어댑터가 계약 보존). */
    private List<FoundPath> findWithRaptor(RaptorInput input, String originStationId,
            String destStationId, int maxCandidates, List<TravelMode> allowedModes,
            KShortestPathFinder.EdgeCostModel costModel) {
        List<com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Route> routes =
                new ArrayList<>();
        Map<String, TravelMode> modeByRouteId = new HashMap<>();
        for (com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Route route
                : input.routeSet().routes()) {
            if (isRaptorModeAllowed(route.mode(), allowedModes)) {
                routes.add(route);
                modeByRouteId.putIfAbsent(route.routeId(), route.mode());
            }
        }
        if (routes.isEmpty()) {
            return List.of();
        }
        List<com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Connection> connections =
                new ArrayList<>();
        for (com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Connection connection
                : input.routeSet().connections()) {
            if (isRaptorModeAllowed(connection.mode(), allowedModes)) {
                connections.add(connection);
            }
        }
        if (input.accessEdges() != null) {
            for (Edge edge : input.accessEdges()) {
                connections.add(new com.ssafy.s15p21a104.domain.route.finder.raptor
                        .RaptorFinder.Connection(edge.fromNode(), edge.toNode(),
                        edge.travelSec(), edge.mode()));
            }
        }
        // 접근·이탈 closure(5부 R-A1) — RAPTOR는 연결을 라운드당 1홉만 이완하므로
        // 연결망 다중 홉(대여소 체인 등)을 경계에서 one-to-many Dijkstra로 만들어 넘긴다.
        // K 재스캔·fast/calm에서 재사용되도록 루프 밖에서 1회 계산한다.
        Map<String, com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Access>
                originAccess = com.ssafy.s15p21a104.domain.route.finder.raptor
                        .RaptorAccessClosure.from(originStationId, connections);
        Map<String, com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Egress>
                destAccess = com.ssafy.s15p21a104.domain.route.finder.raptor
                        .RaptorAccessClosure.to(destStationId, connections);
        boolean minimizeCost = costModel != null;

        // K 후보 전략(217): 첫 스캔 후, 직전 후보의 첫 탑승 구간을 금지해가며 재스캔한다.
        // 라운드별 최선만 나오는 RAPTOR에서 서로 다른 후보를 maxCandidates까지 채운다.
        // 비탑승(전부 연결) 1등이면 금지할 탑승 구간이 없어 수집이 붕괴하므로, 그때는
        // 연결 단독 후보를 건너뛰고 탑승 대안을 계속 모은다(1건만 나가던 원인).
        List<FoundPath> collected = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        Set<String> bannedSegments = new LinkedHashSet<>();
        List<com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Route> currentRoutes =
                routes;
        boolean skipConnectionOnly = false;
        boolean requireTransit = false;
        int runs = 0;
        while (collected.size() < maxCandidates && runs <= RAPTOR_MAX_BAN_RUNS) {
            runs++;
            com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder finder;
            if (minimizeCost) {
                finder = new com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder(
                        currentRoutes, connections,
                        (routeId, fromIdx, toIdx, passThrough, travel) -> costModel.travelCost(
                                new Edge("raptor", "raptor", routeId, travel, 0,
                                        modeByRouteId.getOrDefault(routeId, TravelMode.BUS))));
            } else {
                finder = new com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder(
                        currentRoutes, connections);
            }
            List<com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Journey> journeys =
                    finder.find(originStationId, destStationId,
                            new com.ssafy.s15p21a104.domain.route.finder.raptor
                                    .RaptorFinder.AccessTables(originAccess, destAccess),
                            RAPTOR_MAX_ROUNDS, minimizeCost, requireTransit);
            boolean addedNew = false;
            for (com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Journey journey
                    : journeys) {
                if (skipConnectionOnly && !hasTransit(journey)) {
                    continue;
                }
                java.util.Optional<FoundPath> path =
                        com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorPathAdapter
                                .toFoundPath(journey, currentRoutes,
                                        transferRule.withTable(transferTimes), busRouteIndex);
                if (path.isPresent() && seen.add(pathSignature(path.get()))) {
                    collected.add(path.get());
                    addedNew = true;
                    if (collected.size() >= maxCandidates) {
                        break;
                    }
                }
            }
            if (!addedNew) {
                break;
            }
            Edge firstTransit = firstTransitSegment(collected.get(collected.size() - 1));
            if (firstTransit == null) {
                // 마지막 후보가 비탑승 — 금지할 탑승 구간이 없다. 연결 단독을 건너뛰고
                // 탑승 대안을 한 번 더 모은다(이미 건너뛰었으면 더 없음).
                if (skipConnectionOnly) {
                    break;
                }
                skipConnectionOnly = true;
                requireTransit = true; // 엔진도 '탑승 있는 최선'을 반환하도록(K 수집 붕괴 방지)
                continue;
            }
            bannedSegments.add(firstTransit.fromNode() + "->" + firstTransit.toNode());
            currentRoutes = com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorRouteSetBuilder
                    .withoutSegments(routes, bannedSegments);
            if (currentRoutes.isEmpty()) {
                break;
            }
        }
        return collected;
    }

    /** journey에 탑승(BUS·SUBWAY) leg가 있는가 — 비탑승(전부 연결) 판정용. */
    private static boolean hasTransit(
            com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Journey journey) {
        for (com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder.Leg leg : journey.legs()) {
            if (leg.mode() == TravelMode.BUS || leg.mode() == TravelMode.SUBWAY) {
                return true;
            }
        }
        return false;
    }

    /** 경로의 첫 대중교통 구간 — K 전략에서 다음 후보를 위해 금지할 구간. */
    private static Edge firstTransitSegment(FoundPath path) {
        for (Edge edge : path.edges()) {
            if (edge.mode() == TravelMode.BUS || edge.mode() == TravelMode.SUBWAY) {
                return edge;
            }
        }
        return null;
    }

    /** FoundPath 서명(수단·구간·노선) — K 수집 중 중복 제거용. */
    private static String pathSignature(FoundPath path) {
        StringBuilder signature = new StringBuilder();
        for (Edge edge : path.edges()) {
            signature.append(edge.mode()).append(':').append(edge.fromNode()).append('>')
                    .append(edge.toNode()).append(':').append(edge.routeId()).append('|');
        }
        return signature.toString();
    }

    /** RAPTOR 모드 필터 — WALK·TRANSFER는 연결 구간이라 항상 허용(215 §3.4와 동일 규칙). */
    private static boolean isRaptorModeAllowed(TravelMode mode, List<TravelMode> allowedModes) {
        if (mode == TravelMode.WALK || mode == TravelMode.TRANSFER) {
            return true;
        }
        return allowedModes == null || allowedModes.isEmpty() || allowedModes.contains(mode);
    }

    /** 탐색 결과 1개를 응답 후보로 바꾼다. 재고 게이트 탈락이면 빈 값. */
    private Optional<RouteSearchResponse> toCandidate(FoundPath found, TransferRule rule) {
        List<Edge> edges = found.edges();
        List<RouteMapper.EngineSegment> segments = new java.util.ArrayList<>();
        for (int i = 0; i < edges.size(); i++) {
            Edge edge = edges.get(i);
            // 첫 승차 대기(waitSec)는 첫 leg에 포함시켜 totalMinutes-leg 합을 맞춘다(190 AC3).
            long seconds = edge.travelSec() + (i == 0 ? edge.waitSec() : 0);
            segments.add(new RouteMapper.EngineSegment(
                    edge.fromNode(), edge.toNode(), edge.routeId(), seconds,
                    edge.mode()));
        }
        // 노선 전환 경계마다 환승 소요를 같은 규칙으로 매긴다 (TransferRule 1곳, 232·234).
        // 어댑터(RAPTOR)도 같은 함수를 쓴다 — 집계 불일치로 매퍼 검증이 깨지는 것을 막는다(217 C2).
        List<Long> transferSecs = transferSeconds(found.edges(), rule, busRouteIndex);
        // routeType은 여기서 임의로 SHORTEST를 넣어두고, 전체 후보를 모은 뒤
        // 소요시간 기준으로 다시 매긴다 — 이 시점엔 다른 후보와 비교할 수 없다.
        // 인덱스 전달(234 C1·I2): 매퍼가 같은 교집합 규칙으로 BUS 분리를 해야
        // transferSecs 개수와 경계가 일치한다. null이면 routeId 폴백(기존 동일).
        Optional<RouteSearchResponse> response = RouteMapper.toResponseWithTransfers(
                new RouteMapper.EnginePath(segments, found.totalSec(), found.transferCount()),
                stationInfos, RouteType.SHORTEST, RouteSource.ALGORITHM,
                transferSecs, rentalIds, busRouteIndex);
        return response.filter(r -> BikeStockGate.passesEdges(
                found.edges().stream().map(Edge::fromNode).toList(),
                found.edges().stream().map(Edge::mode).toList(),
                bikeStock.get()));
    }

    /**
     * 엣지 열의 노선 전환 경계 환승 소요 목록(232·234 규칙, TransferRule 단일 정의).
     *
     * <p>RouteMapper도 같은 규칙으로 TRANSFER leg를 만든다 — RAPTOR 어댑터(217)가 이 값을 그대로
     * 써서 transferCount·총계를 맞춘다. 규칙이 갈라지면 매퍼 검증(개수 일치)에서 터진다.
     */
    public static List<Long> transferSeconds(List<Edge> edges, TransferRule rule,
                                             BusRouteIndex busRouteIndex) {
        List<Long> transferSecs = new ArrayList<>();
        Set<String> kept = Set.of();
        TravelMode prevMode = null;
        Set<String> prevOptions = Set.of();
        for (Edge edge : edges) {
            Set<String> options = BusRouteIndex.optionsFor(edge, busRouteIndex);
            if (prevMode != null) {
                TransferRule.TransferDecision decision = TransferRule.decideLines(
                        kept, prevMode, prevOptions, edge.mode(), options);
                if (decision.transfer()) {
                    transferSecs.add(rule.transferCost(edge.fromNode(), kept, options));
                } else if (prevOptions.size() == 1 && options.size() == 1) {
                    // 집합 판정이 닿지 않는 기존 직접 경계(대중교통↔BIKE)는 문자열 규칙 폴백.
                    TransferRule.TransferDecision legacy = TransferRule.decide(
                            singleOrNull(kept), prevMode, prevOptions.iterator().next(),
                            edge.mode(), options.iterator().next());
                    if (legacy.transfer()) {
                        transferSecs.add(rule.costWithStation(
                                0, edge.fromNode(), legacy.costLine(), options.iterator().next()));
                    }
                }
            }
            prevOptions = options;
            kept = TransferRule.keptTransitLines(kept, edge.mode(), options);
            prevMode = edge.mode();
        }
        return transferSecs;
    }

    /** leg의 (수단·출발·도착·노선) 순서로 만든 서명. 같으면 사실상 같은 경로로 보고 중복 제거한다. */
    private static String legSignature(RouteSearchResponse response) {        StringBuilder signature = new StringBuilder();
        for (RouteLegResponse leg : response.legs()) {
            signature.append(leg.mode()).append(':')
                    .append(leg.fromNodeId()).append("->").append(leg.toNodeId()).append(':')
                    .append(leg.routeId()).append('|');
        }
        return signature.toString();
    }

    /**
     * 소요시간순으로 이미 정렬된 후보 목록의 첫 번째를 {@link RouteType#SHORTEST}로,
     * 나머지를 {@link RouteType#ALTERNATIVE}로 다시 매긴다. {@code modes} 필터 "다음"에
     * 호출해야 한다 — 필터로 원래 최단 후보가 빠져도 남은 것 중 첫 번째가 SHORTEST가 된다.
     *
     * @param candidates 시간순 후보 목록
     * @return 라벨 재지정된 후보 목록
     */
    public static List<RouteSearchResponse> relabelByRank(List<RouteSearchResponse> candidates) {
        List<RouteSearchResponse> ranked = new ArrayList<>();
        for (int i = 0; i < candidates.size(); i++) {
            RouteSearchResponse candidate = candidates.get(i);
            RouteType routeType = i == 0 ? RouteType.SHORTEST : RouteType.ALTERNATIVE;
            ranked.add(new RouteSearchResponse(
                    routeType, candidate.totalMinutes(), candidate.legs(), candidate.source(),
                    candidate.totalDistanceMeters(), candidate.transferCount(),
                    candidate.congestionPrediction()));
        }
        return ranked;
    }

    /**
     * 허용 수단만 남긴다. WALK·TRANSFER는 항상 허용(접근·연결용).
     *
     * @param candidates 후보 목록
     * @param modes 허용 수단. null·빈 목록이면 전체 허용
     * @return 필터된 후보 목록
     */
    public static List<RouteSearchResponse> filterByModes(
            List<RouteSearchResponse> candidates, List<TravelMode> modes) {
        if (modes == null || modes.isEmpty()) {
            return candidates;
        }
        return candidates.stream()
                .filter(candidate -> candidate.legs().stream()
                        .allMatch(leg -> isAlwaysAllowed(leg.mode()) || modes.contains(leg.mode())))
                .toList();
    }

    /**
     * {@link #filterByModes}와 같은 규칙을 {@link ScoredCandidate} 목록에 적용한다
     * (S15P21A104-158 — 링크 단위 혼잡도 스코어링이 원본 경로를 계속 들고 있어야 해서).
     */
    public static List<ScoredCandidate> filterScoredByModes(
            List<ScoredCandidate> candidates, List<TravelMode> modes) {
        if (modes == null || modes.isEmpty()) {
            return candidates;
        }
        return candidates.stream()
                .filter(sc -> sc.response().legs().stream()
                        .allMatch(leg -> isAlwaysAllowed(leg.mode()) || modes.contains(leg.mode())))
                .toList();
    }

    private static boolean isAlwaysAllowed(TravelMode mode) {
        return mode == TravelMode.WALK || mode == TravelMode.TRANSFER;
    }

    /**
     * 속도 후보·혼잡 후보를 합치며 완전 중복과 유사경로를 제거한다(S15P21A104-215 후속).
     *
     * <p>제거 기준 두 단계: ① leg 서명 완전 중복(같은 응답이 속도·혼잡 양쪽에서 뽑힌 경우)
     * ② 탄 것만 비교 서명 중복 — 도보·따릉이 접근만 다른 변형은 같은 경로로 본다
     * (설계 3부 §4.1 "탄 것만 비교"). 부족분은 후보 풀에서 시간순으로 채운다.
     *
     * @param speed 시간순 상위(속도) 후보
     * @param calm 혼잡순 상위(혼잡) 후보
     * @param pool 전체 후보(시간순) — 부족분 채움용
     * @param max 합칠 최대 개수
     * @return 중복 제거된 후보 목록(속도 → 혼잡 → 풀 순서 유지)
     */
    public static List<RouteSearchResponse> diversify(
            List<RouteSearchResponse> speed, List<RouteSearchResponse> calm,
            List<RouteSearchResponse> pool, int max) {
        List<RouteSearchResponse> selected = new ArrayList<>(max);
        Map<String, Integer> exactIndex = new LinkedHashMap<>();
        Set<String> transitSignatures = new HashSet<>();
        for (List<RouteSearchResponse> group : List.of(speed, calm, pool)) {
            for (RouteSearchResponse candidate : group) {
                if (selected.size() >= max) {
                    return selected;
                }
                Integer already = exactIndex.get(exactSignature(candidate));
                if (already != null) {
                    // 같은 경로가 속도·혼잡 양쪽에 뽑힌 경우 — 한 번만 두되 ALTERNATIVE면 혼잡
                    // 라벨로 승격한다. SHORTEST(대표 카드)는 라벨을 유지한다.
                    RouteType kept = selected.get(already).routeType();
                    if (candidate.routeType() == RouteType.LOW_CONGESTION
                            && kept != RouteType.LOW_CONGESTION && kept != RouteType.SHORTEST) {
                        selected.set(already, candidate);
                    }
                    continue;
                }
                if (!transitSignatures.add(transitSignature(candidate))) {
                    continue;
                }
                exactIndex.put(exactSignature(candidate), selected.size());
                selected.add(candidate);
            }
        }
        return selected;
    }

    /** leg 단위 (수단·출발·도착·노선) 전체 서명 — 같은 응답 판정. */
    public static String exactSignature(RouteSearchResponse response) {
        StringBuilder signature = new StringBuilder();
        for (RouteLegResponse leg : response.legs()) {
            signature.append(leg.mode()).append(':')
                    .append(leg.fromNodeId()).append('>').append(leg.toNodeId()).append(':')
                    .append(leg.routeId()).append('|');
        }
        return signature.toString();
    }

    /** 탄 것만 — 지하철·버스 leg의 (수단·노선·승하차 지점) 서명. 도보·따릉이·환승은 뺀다. */
    private static String transitSignature(RouteSearchResponse response) {
        StringBuilder signature = new StringBuilder();
        for (RouteLegResponse leg : response.legs()) {
            if (leg.mode() != TravelMode.SUBWAY && leg.mode() != TravelMode.BUS) {
                continue;
            }
            signature.append(leg.mode()).append(':').append(leg.routeId()).append(':')
                    .append(leg.fromNodeId()).append('>').append(leg.toNodeId()).append('|');
        }
        return signature.toString();
    }

    /** BUS가 허용되는 요청인지. null·빈 목록은 전체 허용이다. */
    private static boolean allowsBus(List<TravelMode> allowedModes) {
        return allowedModes == null || allowedModes.isEmpty() || allowedModes.contains(TravelMode.BUS);
    }

    /** BUS만 뺀 허용 수단. 전체 허용(null·빈)이면 BUS를 뺀 기본 3수단으로 좁힌다. */
    private static List<TravelMode> withoutBus(List<TravelMode> allowedModes) {
        if (allowedModes == null || allowedModes.isEmpty()) {
            return List.of(TravelMode.WALK, TravelMode.SUBWAY, TravelMode.BIKE);
        }
        return allowedModes.stream().filter(mode -> mode != TravelMode.BUS).toList();
    }

    /** 단일 원소 집합이면 그 원소, 아니면 null — 기존 문자열 규칙 폴백용(232). */
    private static String singleOrNull(Set<String> lines) {
        if (lines == null || lines.size() != 1) {
            return null;
        }
        return lines.iterator().next();
    }

    /** 휴리스틱 최대 속도(m/s). 데이터의 가장 빠른 간선보다 크게 잡아 과대평가를 막는다. */
    private static final double HEURISTIC_MAX_SPEED_MPS = 40.0;

    /**
     * 목적지까지 남은 시간의 하한(초) — 좌표 직선거리/최대 속도(경로 탐색 구조 4부 §5.2).
     *
     * <p>과대평가하지 않으므로 최단성은 유지되고, 처리 범위만 목적지 방향으로 좁아진다.
     * 좌표가 없으면 0을 돌려 일반 다익스트라와 같아진다.
     */
    private ToLongFunction<String> remainingLowerBound(String destStationId) {
        RouteMapper.StationInfo dest = stationInfos.get(destStationId);
        if (dest == null || dest.lat() == null || dest.lng() == null) {
            return node -> 0L;
        }
        double destLat = dest.lat();
        double destLng = dest.lng();
        return node -> {
            RouteMapper.StationInfo info = stationInfos.get(node);
            if (info == null || info.lat() == null || info.lng() == null) {
                return 0L;
            }
            double meters = GeoDistance.haversineMeters(info.lat(), info.lng(), destLat, destLng);
            return (long) (meters / HEURISTIC_MAX_SPEED_MPS);
        };
    }
}
