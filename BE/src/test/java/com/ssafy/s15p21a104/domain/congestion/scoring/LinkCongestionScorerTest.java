package com.ssafy.s15p21a104.domain.congestion.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-158(통지 05 S-1): 링크 단위·통과 시각 슬롯 기반 혼잡도 스코어링 순수 함수 검증.
 */
class LinkCongestionScorerTest {

    private static final LocalDateTime DEPARTURE = LocalDateTime.of(2026, 9, 18, 8, 0);

    @Test
    @DisplayName("엣지마다 통과 시각(누적 travelSec+waitSec)이 다르게 넘어온다")
    void 통과시각_누적() {
        Edge first = subwayEdge("A", "B", 600, 60); // 10분 + 대기 1분
        Edge second = subwayEdge("B", "C", 300, 0); // 5분

        List<LocalDateTime> seenTimes = new java.util.ArrayList<>();
        LinkCongestionScorer.score(List.of(first, second), DEPARTURE, (edge, passThroughTime) -> {
            seenTimes.add(passThroughTime);
            return 50.0;
        });

        assertEquals(DEPARTURE, seenTimes.get(0));
        assertEquals(DEPARTURE.plusSeconds(660), seenTimes.get(1));
    }

    @Test
    @DisplayName("소요시간(travelSec) 가중 평균으로 계산한다 — 대기시간은 가중치에 안 들어간다")
    void 소요시간_가중평균() {
        Edge first = subwayEdge("A", "B", 600, 300); // 10분, 혼잡도 20
        Edge second = subwayEdge("B", "C", 1800, 0); // 30분, 혼잡도 60

        LinkCongestionScorer.Result result = LinkCongestionScorer.score(
                List.of(first, second), DEPARTURE,
                (edge, passThroughTime) -> edge.fromNode().equals("A") ? 20.0 : 60.0).orElseThrow();

        // (20*600 + 60*1800) / (600+1800) = (12000+108000)/2400 = 50
        assertEquals(50.0, result.weightedAverage(), 1e-9);
    }

    @Test
    @DisplayName("혼잡도를 아는 SUBWAY 엣지가 하나도 없으면 빈 값이다(값을 지어내지 않음)")
    void 데이터없음_빈값() {
        Edge edge = subwayEdge("A", "B", 600, 0);

        Optional<LinkCongestionScorer.Result> result =
                LinkCongestionScorer.score(List.of(edge), DEPARTURE, (e, t) -> null);

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("방향을 몰라 lookup이 null을 주는 엣지는 결측과 같이 건너뛴다")
    void 방향모름_건너뜀() {
        Edge known = subwayEdge("A", "B", 600, 0);
        Edge unknownDirection = subwayEdge("B", "C", 1800, 0);

        LinkCongestionScorer.Result result = LinkCongestionScorer.score(
                List.of(known, unknownDirection), DEPARTURE,
                (edge, passThroughTime) -> edge.fromNode().equals("A") ? 40.0 : null).orElseThrow();

        assertEquals(40.0, result.weightedAverage(), 1e-9);
    }

    @Test
    @DisplayName("WALK·BIKE 등 비지하철 엣지는 통과시각 누적에는 반영되지만 점수에서는 제외한다")
    void 비지하철_엣지_제외() {
        Edge walk = new Edge("A", "B", "WALK", 120, 0, TravelMode.WALK);
        Edge subway = subwayEdge("B", "C", 600, 0);

        List<LocalDateTime> seenTimes = new java.util.ArrayList<>();
        LinkCongestionScorer.Result result = LinkCongestionScorer.score(
                List.of(walk, subway), DEPARTURE, (edge, passThroughTime) -> {
                    seenTimes.add(passThroughTime);
                    return 70.0;
                }).orElseThrow();

        assertEquals(70.0, result.weightedAverage(), 1e-9);
        // WALK 엣지는 lookup이 안 불려도(비지하철 필터가 먼저 걸러도) 되지만,
        // 불렸다면 통과시각은 누적 반영된 이후 시각이어야 한다.
        assertTrue(seenTimes.isEmpty() || seenTimes.get(0).equals(DEPARTURE.plusSeconds(120)));
    }

    @Test
    @DisplayName("혼잡도가 가장 높은 엣지를 worstEdge로 추적한다(표시용)")
    void 최악_링크_추적() {
        Edge low = subwayEdge("A", "B", 600, 0);
        Edge high = subwayEdge("B", "C", 600, 0);
        Edge mid = subwayEdge("C", "D", 600, 0);

        LinkCongestionScorer.Result result = LinkCongestionScorer.score(
                List.of(low, high, mid), DEPARTURE, (edge, passThroughTime) -> switch (edge.fromNode()) {
                    case "A" -> 30.0;
                    case "B" -> 90.0;
                    default -> 50.0;
                }).orElseThrow();

        assertEquals(high, result.worstEdge());
        assertEquals(90.0, result.worstLevel(), 1e-9);
    }

    @Test
    @DisplayName("결측 엣지는 worstEdge 후보에서 제외된다")
    void 결측_worst후보_제외() {
        Edge known = subwayEdge("A", "B", 600, 0);
        Edge missing = subwayEdge("B", "C", 600, 0);

        LinkCongestionScorer.Result result = LinkCongestionScorer.score(
                List.of(known, missing), DEPARTURE,
                (edge, passThroughTime) -> edge.fromNode().equals("A") ? 55.0 : null).orElseThrow();

        assertEquals(known, result.worstEdge());
        assertNull(LinkCongestionScorer.score(List.of(missing), DEPARTURE, (e, t) -> null)
                .map(LinkCongestionScorer.Result::worstEdge).orElse(null));
    }

    private static Edge subwayEdge(String from, String to, int travelSec, int waitSec) {
        return new Edge(from, to, "L1", travelSec, waitSec, TravelMode.SUBWAY);
    }
}
