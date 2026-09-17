package com.ssafy.s15p21a104.domain.route.scoring;

import com.ssafy.s15p21a104.domain.congestion.scoring.CongestionScorer;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 쾌적 우선 재정렬(S15P21A104-213 T4).
 *
 * <p>{@code RouteSearchService}에서 분리했다. 혼잡도 점수 조회 함수를 주입받아
 * 후보들을 혼잡도 오름차순으로 재정렬하고 가장 쾌적한 후보를
 * {@link RouteType#LOW_CONGESTION}으로 표시한다(S15P21A104-157).
 * 혼잡도 데이터가 하나도 없으면 순서를 건드리지 않는다 — 혼잡도를 반영한 척하지
 * 않는다(값을 지어내지 않는다는 원칙).
 */
public final class RouteScoreRanker {

    /** 혼잡도 점수 조회: (targetType, targetId, dowType, timeSlot). 없으면 null. */
    @FunctionalInterface
    public interface CongestionLevelLookup {
        Double find(String targetType, String targetId, int dowType, int timeSlot);
    }

    private final CongestionLevelLookup levelLookup;

    /**
     * @param levelLookup 혼잡도 점수 조회
     */
    public RouteScoreRanker(CongestionLevelLookup levelLookup) {
        this.levelLookup = levelLookup;
    }

    /**
     * 혼잡도가 가장 낮은 후보를 맨 앞으로 재정렬하고 LOW_CONGESTION으로 표시한다.
     *
     * @param candidates 시간순 정렬된 후보 목록
     * @param dowType 요일 구분
     * @param timeSlot 시간 슬롯
     * @return 재정렬된 후보 목록. 데이터 없으면 원본 그대로
     */
    public List<RouteSearchResponse> applyComfort(
            List<RouteSearchResponse> candidates, int dowType, int timeSlot) {
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
            Double level = levelLookup.find("LINE", routeId, dowType, timeSlot);
            if (level != null) {
                levelByRouteId.put(routeId, level);
            }
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
}
