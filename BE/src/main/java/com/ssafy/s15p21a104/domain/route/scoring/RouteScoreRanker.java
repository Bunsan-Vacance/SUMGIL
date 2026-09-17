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
     * 데이터 없으면 원본 그대로 둔다(값을 지어내지 않음).
     *
     * @param candidates 시간순 정렬된 후보 목록
     * @param dowType 요일 구분
     * @param timeSlot 시간 슬롯
     * @return 재정렬된 후보 목록. 데이터 없으면 원본 그대로
     */
    public List<RouteSearchResponse> applyComfort(
            List<RouteSearchResponse> candidates, int dowType, int timeSlot) {
        List<RouteSearchResponse> calm = topCalm(candidates, dowType, timeSlot,
                candidates == null ? 0 : candidates.size());
        if (calm.isEmpty()) {
            return candidates;
        }
        // topCalm은 상위 전체를 ALTERNATIVE로 다시 매기므로, 원본 순서를 유지한 채
        // LOW_CONGESTION 1개만 맨 앞으로 옮긴 형태로 되돌린다.
        Set<String> calmSignatures = new java.util.HashSet<>();
        for (RouteSearchResponse c : calm) {
            calmSignatures.add(signatureOf(c));
        }
        RouteSearchResponse lowest = calm.get(0);
        List<RouteSearchResponse> result = new ArrayList<>();
        result.add(lowest);
        for (RouteSearchResponse candidate : candidates) {
            if (signatureOf(candidate).equals(signatureOf(lowest))) {
                continue;
            }
            result.add(candidate);
        }
        return result;
    }

    private static String signatureOf(RouteSearchResponse response) {
        StringBuilder signature = new StringBuilder();
        for (RouteLegResponse leg : response.legs()) {
            signature.append(leg.mode()).append(':')
                    .append(leg.fromNodeId()).append("->").append(leg.toNodeId()).append(':')
                    .append(leg.routeId()).append('|');
        }
        return signature.toString();
    }

    /**
     * 혼잡순 상위 N개를 뽑는다(S15P21A104-214). 맨 앞은 LOW_CONGESTION, 나머지는
     * ALTERNATIVE로 표시한다. 혼잡도 데이터가 하나도 없으면 빈 목록 — 값을 지어내지 않는다.
     *
     * @param candidates 시간순 정렬된 후보 목록
     * @param dowType 요일 구분
     * @param timeSlot 시간 슬롯
     * @param n 최대 개수
     * @return 혼잡순 상위 목록 (최대 n개). 데이터 없으면 빈 목록
     */
    public List<RouteSearchResponse> topCalm(
            List<RouteSearchResponse> candidates, int dowType, int timeSlot, int n) {
        Set<String> subwayRouteIds = new HashSet<>();
        for (RouteSearchResponse candidate : candidates) {
            for (RouteLegResponse leg : candidate.legs()) {
                if (leg.mode() == TravelMode.SUBWAY && leg.routeId() != null) {
                    subwayRouteIds.add(leg.routeId());
                }
            }
        }
        if (subwayRouteIds.isEmpty()) {
            return List.of();
        }
        Map<String, Double> levelByRouteId = new HashMap<>();
        for (String routeId : subwayRouteIds) {
            Double level = levelLookup.find("LINE", routeId, dowType, timeSlot);
            if (level != null) {
                levelByRouteId.put(routeId, level);
            }
        }
        if (levelByRouteId.isEmpty()) {
            return List.of();
        }

        Map<RouteSearchResponse, Double> scoreByCandidate = new HashMap<>();
        for (RouteSearchResponse candidate : candidates) {
            CongestionScorer.score(candidate.legs(), levelByRouteId)
                    .ifPresent(score -> scoreByCandidate.put(candidate, score));
        }
        if (scoreByCandidate.isEmpty()) {
            return List.of();
        }

        // 점수 있는 후보만 혼잡순에 넣는다. 점수 없는 후보를 끼우면 순위 조작이다.
        List<RouteSearchResponse> scored = new ArrayList<>(scoreByCandidate.keySet());
        scored.sort(Comparator.comparingDouble(
                candidate -> scoreByCandidate.getOrDefault(candidate, Double.MAX_VALUE)));

        List<RouteSearchResponse> relabeled = new ArrayList<>();
        boolean lowestTagged = false;
        for (RouteSearchResponse candidate : scored) {
            if (relabeled.size() >= n) {
                break;
            }
            if (!lowestTagged) {
                relabeled.add(new RouteSearchResponse(
                        RouteType.LOW_CONGESTION, candidate.totalMinutes(), candidate.legs(),
                        candidate.source(), candidate.totalDistanceMeters(), candidate.transferCount()));
                lowestTagged = true;
            } else {
                relabeled.add(new RouteSearchResponse(
                        RouteType.ALTERNATIVE, candidate.totalMinutes(), candidate.legs(),
                        candidate.source(), candidate.totalDistanceMeters(), candidate.transferCount()));
            }
        }
        return relabeled;
    }
}
