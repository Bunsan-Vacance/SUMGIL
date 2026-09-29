package com.ssafy.s15p21a104.domain.route.scoring;

import com.ssafy.s15p21a104.domain.congestion.scoring.CongestionScorer;
import com.ssafy.s15p21a104.domain.congestion.scoring.LinkCongestionScorer;
import com.ssafy.s15p21a104.domain.route.dto.response.PredictionBasis;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.WorstSegmentResponse;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.Optional;
import java.util.function.Function;

/**
 * 혼잡 최악값 선택(2026-09-22) — 링크 예측·BUS 실시간·노선 통계 폴백 중 "가장 혼잡한 구간"
 * 하나를 골라 응답 계약({@link CongestionPredictionResolver.Worst})으로 바꾼다.
 *
 * <p>우선순위: 링크 예측(RECENT_7D) &gt; BUS 실시간(LIVE) &gt; 노선 통계(WEEKDAY_AVERAGE).
 * 값이 같으면 앞의 근거가 이긴다. 노선 통계는 링크·BUS가 하나도 없을 때만 쓴다 — 값이 있는
 * 경로의 정렬과 표시가 갈라지지 않게 하기 위해서다.
 *
 * <p>순수 함수이며 DB·Spring에 의존하지 않는다.
 */
public final class WorstCongestionPicker {

    private WorstCongestionPicker() {
    }

    /**
     * @param link 링크 단위 채점 결과(없으면 빈 값)
     * @param stationName 역 ID → 표시명(링크 구간은 leg에 이름이 없어 따로 해석한다)
     * @param bus BUS leg 최악(없으면 빈 값)
     * @param line 노선 통계 최악(없으면 빈 값)
     * @return 최악 구간. 아는 값이 하나도 없으면 빈 값 — 값을 지어내지 않는다
     */
    public static Optional<CongestionPredictionResolver.Worst> pick(
            Optional<LinkCongestionScorer.Result> link,
            Function<String, String> stationName,
            Optional<CongestionScorer.Worst> bus,
            Optional<CongestionScorer.Worst> line) {
        if (link.isPresent()) {
            LinkCongestionScorer.Result value = link.get();
            if (bus.isPresent() && bus.get().level() > value.worstLevel()) {
                return Optional.of(busPick(bus.get()));
            }
            Edge edge = value.worstEdge();
            WorstSegmentResponse segment = new WorstSegmentResponse(
                    edge.mode(),
                    edge.fromNode(), stationName.apply(edge.fromNode()),
                    edge.toNode(), stationName.apply(edge.toNode()),
                    value.worstLevel());
            return Optional.of(new CongestionPredictionResolver.Worst(
                    value.worstLevel(), PredictionBasis.RECENT_7D, segment));
        }
        if (bus.isPresent()) {
            return Optional.of(busPick(bus.get()));
        }
        if (line.isPresent()) {
            CongestionScorer.Worst value = line.get();
            return Optional.of(new CongestionPredictionResolver.Worst(
                    value.level(), PredictionBasis.WEEKDAY_AVERAGE, segmentOf(value)));
        }
        return Optional.empty();
    }

    private static CongestionPredictionResolver.Worst busPick(CongestionScorer.Worst worst) {
        return new CongestionPredictionResolver.Worst(worst.level(), PredictionBasis.LIVE, segmentOf(worst));
    }

    private static WorstSegmentResponse segmentOf(CongestionScorer.Worst worst) {
        RouteLegResponse leg = worst.leg();
        return new WorstSegmentResponse(leg.mode(), leg.fromNodeId(), leg.fromNodeName(),
                leg.toNodeId(), leg.toNodeName(), worst.level());
    }
}
