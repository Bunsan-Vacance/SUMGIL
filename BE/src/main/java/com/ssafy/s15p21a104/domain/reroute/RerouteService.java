package com.ssafy.s15p21a104.domain.reroute;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.finder.ScoredCandidate;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
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

    /** 잔여 안내 고정 문구 (FE 표시용). */
    private static final String REMAIN_REASON = "현재 경계에서 남은 시간을 다시 계산했어요.";

    private final RouteCandidateFinder candidateFinder;
    private final java.util.function.Supplier<RouteGraph> graphSupplier;

    /**
     * @param candidateFinder 잔여 매핑용 조립기 (그래프·역정보 주입済)
     * @param graphSupplier 탐색 그래프 공급자
     */
    public RerouteService(RouteCandidateFinder candidateFinder,
                          java.util.function.Supplier<RouteGraph> graphSupplier) {
        this.candidateFinder = candidateFinder;
        this.graphSupplier = graphSupplier;
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
        // findCandidatesWithPaths가 leg 서명 중복 제거된 서로 다른 후보를 시간순으로 준다.
        // 후보마다 동일 인자로 재탐색하던 기존 toResult는 같은 1등만 반복했다.
        // 실패는 은폐하지 않는다(5부 D1, fail-fast) — 연결 불가는 빈 목록으로 구분된다.
        List<ScoredCandidate> scored =
                candidateFinder.findCandidatesWithPaths(graph, boundaryId, destId, MAX_REMAIN);
        List<RerouteResult> result = new ArrayList<>();
        for (ScoredCandidate candidate : scored) {
            RouteSearchResponse route = candidate.response();
            // 잔여 legs만 담고 totalMinutes는 잔여 합과 일치시킨다(FE §5.2 ±0.01).
            // 대기 분리(2026-09-22) 후에는 leg 소요(이동) + waitMinutes 합이다.
            double sum = route.legs().stream()
                    .mapToDouble(leg -> leg.minutes()
                            + (leg.waitMinutes() == null ? 0 : leg.waitMinutes()))
                    .sum();
            RouteSearchResponse remain = new RouteSearchResponse(
                    route.routeType(), sum, route.legs(), RouteSource.ALGORITHM,
                    route.totalDistanceMeters(), route.transferCount(),
                    route.congestionPrediction());
            result.add(new RerouteResult(REMAIN_REASON, "ALGORITHM", remain));
            if (result.size() >= MAX_REMAIN) {
                break;
            }
        }
        result.sort(Comparator.comparingDouble(r -> r.route().totalMinutes()));
        return List.copyOf(result);
    }

    private RouteGraph graphOf() {
        return graphSupplier.get();
    }
}
