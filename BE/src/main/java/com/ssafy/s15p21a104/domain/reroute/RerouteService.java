package com.ssafy.s15p21a104.domain.reroute;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.KShortestPathFinder;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * 잔여 경로 재탐색(S15P21A104-193, FE 문서 §5.2 계약).
 *
 * <p>현 경계(boundary)부터 목적지까지 탐색 1회로 잔여 후보를 뽑는다.
 * 전체 그래프 재탐색을 전제하지 않고, 세션 없이 stateless로 동작한다
 * (currentRoute.id는 FE 세션 ID라 서버에 저장하지 않는다).
 * 153·157 점수/COMFORT 로직은 재사용하며 재구현하지 않는다.
 */
public final class RerouteService {

    /** 잔여 후보 상한. */
    private static final int MAX_REMAIN = 3;

    private final RouteCandidateFinder candidateFinder;
    private final TransferRule transferRule;
    private final java.util.function.Supplier<RouteGraph> graphSupplier;
    private final java.util.function.Supplier<java.util.Map<TransferRule.TransferKey, Integer>> transferTimesSupplier;

    /**
     * @param candidateFinder 잔여 매핑용 조립기 (그래프·역정보 주입済)
     * @param transferRule 환승 규칙
     * @param graphSupplier 탐색 그래프 공급자
     * @param transferTimesSupplier 환승 실측표 공급자
     */
    public RerouteService(RouteCandidateFinder candidateFinder, TransferRule transferRule,
                          java.util.function.Supplier<RouteGraph> graphSupplier,
                          java.util.function.Supplier<java.util.Map<TransferRule.TransferKey, Integer>> transferTimesSupplier) {
        this.candidateFinder = candidateFinder;
        this.transferRule = transferRule;
        this.graphSupplier = graphSupplier;
        this.transferTimesSupplier = transferTimesSupplier;
    }

    /**
     * 현 경계부터 목적지까지 잔여 후보를 찾는다.
     *
     * @param boundaryId 현 경계 노드 ID
     * @param destId 목적지 노드 ID
     * @param dowType 요일 구분
     * @param timeSlot 시간 슬롯
     * @return 잔여 후보 (시간순, 최대 3개). 연결 불가면 빈 목록
     */
    public List<RerouteResult> replan(String boundaryId, String destId, int dowType, int timeSlot) {
        if (boundaryId == null || destId == null || boundaryId.equals(destId)) {
            return List.of();
        }
        RouteGraph graph = graphOf();
        if (graph == null || !graph.containsNode(boundaryId) || !graph.containsNode(destId)) {
            return List.of();
        }
        List<FoundPath> paths;
        try {
            paths = new KShortestPathFinder(transferRule.withTable(transferTimes()))
                    .findK(graph, boundaryId, destId, MAX_REMAIN);
        } catch (RuntimeException e) {
            return List.of();
        }
        List<RerouteResult> result = new ArrayList<>();
        for (FoundPath found : paths) {
            toResult(found, boundaryId, destId).ifPresent(result::add);
            if (result.size() >= MAX_REMAIN) {
                break;
            }
        }
        result.sort(Comparator.comparingDouble(r -> r.route().totalMinutes()));
        return List.copyOf(result);
    }

    private java.util.Optional<RerouteResult> toResult(FoundPath found, String boundaryId, String destId) {
        // RouteCandidateFinder에 단일 경로 매핑을 위임할 수 없어 여기서 직접 조립한다.
        // 잔여 legs만 담고 totalMinutes는 잔여 합과 일치시킨다(FE §5.2 ±0.01).
        List<RouteSearchResponse> mapped = candidateFinder.findCandidates(
                graphOf(), boundaryId, destId, 1);
        if (mapped.isEmpty()) {
            return java.util.Optional.empty();
        }
        RouteSearchResponse route = mapped.get(0);
        double sum = route.legs().stream().mapToDouble(RouteLegResponse::minutes).sum();
        RouteSearchResponse remain = new RouteSearchResponse(
                route.routeType(), sum, route.legs(), RouteSource.ALGORITHM,
                route.totalDistanceMeters(), route.transferCount());
        return java.util.Optional.of(new RerouteResult(
                "현재 경계에서 남은 시간을 다시 계산했어요.", "ALGORITHM", remain));
    }

    private RouteGraph graphOf() {
        return graphSupplier.get();
    }

    private java.util.Map<TransferRule.TransferKey, Integer> transferTimes() {
        return transferTimesSupplier.get();
    }
}
