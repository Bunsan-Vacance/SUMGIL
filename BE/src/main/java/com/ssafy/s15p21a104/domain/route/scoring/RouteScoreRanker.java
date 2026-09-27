package com.ssafy.s15p21a104.domain.route.scoring;

import com.ssafy.s15p21a104.domain.congestion.scoring.CongestionScorer;
import com.ssafy.s15p21a104.domain.congestion.scoring.LinkCongestionScorer;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.ScoredCandidate;
import java.time.LocalDateTime;
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
            CongestionScorer.worst(candidate.legs(), levelByRouteId)
                    .ifPresent(worst -> scoreByCandidate.put(candidate, worst.level()));
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
                        candidate.source(), candidate.totalDistanceMeters(), candidate.transferCount(),
                        candidate.congestionPrediction()));
                lowestTagged = true;
            } else {
                relabeled.add(new RouteSearchResponse(
                        RouteType.ALTERNATIVE, candidate.totalMinutes(), candidate.legs(),
                        candidate.source(), candidate.totalDistanceMeters(), candidate.transferCount(),
                        candidate.congestionPrediction()));
            }
        }
        return relabeled;
    }

    /**
     * 링크 단위·통과 시각 슬롯 기반 혼잡순 상위 N개(S15P21A104-158, 통지 05 S-1).
     * {@link #topCalm}(노선 단위·출발 슬롯 1개)을 대체한다 — 같은 노선을 여러 정거장
     * 타는 leg도 원본 엣지({@link ScoredCandidate#path()})로 되돌아가 엣지마다 실제
     * 통과 시각의 혼잡도를 조회한다.
     *
     * @param candidates 응답+원본 경로 목록
     * @param departureTime 출발 시각(엣지별 통과 시각 계산의 기준)
     * @param lookup 엣지·통과시각으로 혼잡도를 조회하는 함수(방향 판정 포함, 모르면 null)
     * @param n 최대 개수
     * @return 혼잡순 상위 목록(최대 n개). 혼잡도 데이터가 하나도 없으면 빈 목록
     */
    /** BUS leg → 공통 수치 혼잡(5부 C1). 모르면 null(중립). */
    @FunctionalInterface
    public interface BusLevelLookup {
        Double levelOf(RouteLegResponse leg);
    }

    public List<RouteSearchResponse> topCalmByLink(
            List<ScoredCandidate> candidates, LocalDateTime departureTime,
            LinkCongestionScorer.LinkLevelLookup lookup, int n) {
        return topCalmByLink(candidates, departureTime, lookup, n, null);
    }

    /**
     * @param busLevels BUS leg 혼잡 수치 조회(5부 C1, 선택). null이면 지하철 링크만으로 채점
     */
    public List<RouteSearchResponse> topCalmByLink(
            List<ScoredCandidate> candidates, LocalDateTime departureTime,
            LinkCongestionScorer.LinkLevelLookup lookup, int n, BusLevelLookup busLevels) {
        // 입력(시간순) 순서 유지 — HashMap 순회는 enum 해시 때문에 실행마다 달라진다(271).
        Map<RouteSearchResponse, Double> scoreByCandidate = new java.util.LinkedHashMap<>();
        for (ScoredCandidate candidate : candidates) {
            Double score = worstScore(candidate, departureTime, lookup, busLevels);
            if (score != null) {
                scoreByCandidate.put(candidate.response(), score);
            }
        }
        if (scoreByCandidate.isEmpty()) {
            return List.of();
        }

        // 점수 있는 후보만 혼잡순에 넣는다. 점수 없는 후보를 끼우면 순위 조작이다.
        // 동점은 소요시간 짧은 순(271).
        List<RouteSearchResponse> scored = new ArrayList<>(scoreByCandidate.keySet());
        scored.sort(Comparator.<RouteSearchResponse>comparingDouble(
                candidate -> scoreByCandidate.getOrDefault(candidate, Double.MAX_VALUE))
                .thenComparingDouble(RouteSearchResponse::totalMinutes));

        List<RouteSearchResponse> relabeled = new ArrayList<>();
        boolean lowestTagged = false;
        for (RouteSearchResponse candidate : scored) {
            if (relabeled.size() >= n) {
                break;
            }
            RouteType routeType = lowestTagged ? RouteType.ALTERNATIVE : RouteType.LOW_CONGESTION;
            lowestTagged = true;
            relabeled.add(new RouteSearchResponse(
                    routeType, candidate.totalMinutes(), candidate.legs(),
                    candidate.source(), candidate.totalDistanceMeters(), candidate.transferCount(),
                    candidate.congestionPrediction()));
        }
        return relabeled;
    }

    /**
     * 지하철 링크 최대값 + BUS 등급(공통 축) 중 <b>최대</b> — "가장 혼잡한 구간" 기준
     * (2026-09-22 표시·정렬 통일). 아는 값이 하나도 없으면 null — 혼잡도로 비교할 수 없는 후보다.
     */
    private static Double worstScore(ScoredCandidate candidate, LocalDateTime departureTime,
            LinkCongestionScorer.LinkLevelLookup lookup, BusLevelLookup busLevels) {
        Double worst = null;
        var link = LinkCongestionScorer.score(candidate.path().edges(), departureTime, lookup);
        if (link.isPresent()) {
            worst = link.get().worstLevel();
        }
        if (busLevels != null) {
            for (RouteLegResponse leg : candidate.response().legs()) {
                if (leg.mode() != TravelMode.BUS) {
                    continue;
                }
                Double level = busLevels.levelOf(leg);
                if (level == null) {
                    continue;
                }
                if (worst == null || level > worst) {
                    worst = level;
                }
            }
        }
        return worst;
    }
}
