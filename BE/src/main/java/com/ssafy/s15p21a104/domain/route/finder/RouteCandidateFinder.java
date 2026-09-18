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
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Supplier;

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
        this.transferRule = transferRule;
        this.transferTimes = transferTimes;
        this.rentalIds = rentalIds;
        this.stationInfos = stationInfos;
        this.bikeStock = bikeStock;
        this.busRouteIndex = busRouteIndex;
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
        // 그래프 슬롯 선택과 탑승 시 wait_sec 가산(96/104 후속, 전우석)이 붙으면 여기서 넘긴다.
        TransferRule rule = transferRule.withTable(transferTimes);

        List<FoundPath> paths =
                new KShortestPathFinder(rule, busRouteIndex).findK(graph, originStationId, destStationId, maxCandidates);

        Map<String, RouteSearchResponse> byLegSignature = new LinkedHashMap<>();
        for (FoundPath found : paths) {
            toCandidate(found, rule)
                    .ifPresent(candidate -> byLegSignature.putIfAbsent(legSignature(candidate), candidate));
        }

        return byLegSignature.values().stream()
                .sorted(Comparator.comparingDouble(RouteSearchResponse::totalMinutes))
                .limit(maxCandidates)
                .toList();
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
        // WALK를 지나도 유지된 대중교통 노선 집합으로 비교한다.
        List<Long> transferSecs = new ArrayList<>();
        Set<String> kept = Set.of();
        String keptStr = null;
        TravelMode prevMode = null;
        Set<String> prevOptions = Set.of();
        for (Edge edge : found.edges()) {
            Set<String> options = BusRouteIndex.optionsFor(edge, busRouteIndex);
            if (prevMode != null) {
                TransferRule.TransferDecision decision = TransferRule.decideLines(
                        kept, prevMode, prevOptions, edge.mode(), options);
                if (decision.transfer()) {
                    transferSecs.add(rule.transferCost(edge.fromNode(), kept, options));
                } else if (prevOptions.size() == 1 && options.size() == 1) {
                    // 집합 판정이 닿지 않는 기존 직접 경계(대중교통↔BIKE)는 문자열 규칙으로
                    // 그대로 본다 — 단일 노선 그래프에서 232와 바이트 동일.
                    TransferRule.TransferDecision legacy = TransferRule.decide(
                            keptStr, prevMode, prevOptions.iterator().next(),
                            edge.mode(), options.iterator().next());
                    if (legacy.transfer()) {
                        transferSecs.add(rule.costWithStation(
                                0, edge.fromNode(), legacy.costLine(), options.iterator().next()));
                    }
                }
            }
            prevOptions = options;
            kept = TransferRule.keptTransitLines(kept, edge.mode(), options);
            keptStr = TransferRule.keptTransitLine(keptStr, edge.mode(), edge.routeId());
            prevMode = edge.mode();
        }
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

    /** leg의 (수단·출발·도착·노선) 순서로 만든 서명. 같으면 사실상 같은 경로로 보고 중복 제거한다. */
    private static String legSignature(RouteSearchResponse response) {
        StringBuilder signature = new StringBuilder();
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
                    candidate.totalDistanceMeters(), candidate.transferCount()));
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

    private static boolean isAlwaysAllowed(TravelMode mode) {
        return mode == TravelMode.WALK || mode == TravelMode.TRANSFER;
    }
}
