package com.ssafy.s15p21a104.domain.congestion.scoring;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

/**
 * 경로 후보(원 엣지 목록)의 링크 단위 혼잡도 점수를 계산한다(S15P21A104-158, 통지 05 S-1).
 *
 * <p>순수 함수이며 DB·Spring에 의존하지 않는다. {@link CongestionScorer}(157, 노선 단위·
 * 출발 슬롯 1개)를 대체한다 — 이제 SUBWAY 엣지마다 그 엣지를 실제로 통과하는 시각의
 * 혼잡도를 조회한다. 시각은 출발 시각에 앞선 엣지들의 {@code travelSec+waitSec}를
 * 누적해서 구한다({@link Edge#travelSec()}·{@link Edge#waitSec()}).
 *
 * <p>조회 자체(테이블 조회·방향 판정)는 {@link LinkLevelLookup}으로 주입받는다 — 방향
 * 판정 예외표(2호선 지선 등)가 아직 확정되지 않았는데, 이 클래스가 그 판정 방법을
 * 몰라야 예외표가 나중에 채워져도 이 클래스는 안 건드린다. 방향을 모르면 호출부가
 * {@code null}을 돌려주면 되고, 그 엣지는 결측과 똑같이 건너뛴다(값을 지어내지 않음).
 */
public final class LinkCongestionScorer {

    private LinkCongestionScorer() {
    }

    @FunctionalInterface
    public interface LinkLevelLookup {
        /**
         * @param edge 지하철 링크(엣지)
         * @param passThroughTime 이 엣지에 진입하는 시각(누적 travelSec+waitSec 반영)
         * @return 그 시각 그 링크의 혼잡도(%). 모르면(방향 미정·결측·비지하철 등) null
         */
        Double find(Edge edge, LocalDateTime passThroughTime);
    }

    /**
     * @param weightedAverage 소요시간(travelSec) 가중 평균 혼잡도(%) — 정렬용
     * @param worstEdge 값을 아는 엣지 중 혼잡도가 가장 높은 엣지 — 표시용
     * @param worstLevel worstEdge의 혼잡도(%)
     */
    public record Result(double weightedAverage, Edge worstEdge, double worstLevel) {
    }

    /**
     * @param edges 경로 후보의 원 엣지 목록(순서대로, {@code FoundPath.edges()})
     * @param departureTime 이 후보의 출발 시각
     * @param lookup 엣지·통과시각으로 혼잡도를 조회하는 함수
     * @return 혼잡도를 아는 SUBWAY 엣지가 하나도 없으면 빈 값 — 이 경로는 혼잡도로 비교할 수 없다는 뜻
     */
    public static Optional<Result> score(List<Edge> edges, LocalDateTime departureTime, LinkLevelLookup lookup) {
        double weightedSum = 0;
        long knownSec = 0;
        Edge worstEdge = null;
        double worstLevel = Double.NEGATIVE_INFINITY;
        long cumulativeSec = 0;

        for (Edge edge : edges) {
            LocalDateTime passThroughTime = departureTime.plusSeconds(cumulativeSec);
            cumulativeSec += edge.travelSec() + edge.waitSec();

            if (edge.mode() != TravelMode.SUBWAY) {
                continue;
            }
            Double level = lookup.find(edge, passThroughTime);
            if (level == null) {
                continue;
            }
            // 혼잡한 채로 타고 있는 시간(travelSec)으로 가중한다 — 대기(waitSec)는
            // 플랫폼에 있는 시간이지 그 링크의 혼잡도를 겪는 시간이 아니다.
            weightedSum += level * edge.travelSec();
            knownSec += edge.travelSec();
            if (level > worstLevel) {
                worstLevel = level;
                worstEdge = edge;
            }
        }

        if (knownSec <= 0) {
            return Optional.empty();
        }
        return Optional.of(new Result(weightedSum / knownSec, worstEdge, worstLevel));
    }
}
