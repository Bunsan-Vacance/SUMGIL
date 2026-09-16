package com.ssafy.s15p21a104.domain.congestion.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-157(원래 S15P21A104-153 범위): 혼잡도 기반 경로 스코어링 순수 함수 검증.
 */
class CongestionScorerTest {

    @Test
    @DisplayName("혼잡도가 다른 두 경로를 넣으면 낮은 쪽 점수가 더 좋게(낮게) 나온다")
    void 혼잡도_낮은쪽이_낮은점수() {
        List<RouteLegResponse> lowCongestion = List.of(subwayLeg("L1", 10.0));
        List<RouteLegResponse> highCongestion = List.of(subwayLeg("L2", 10.0));
        Map<String, Double> levels = Map.of("L1", 30.0, "L2", 80.0);

        double lowScore = CongestionScorer.score(lowCongestion, levels).orElseThrow();
        double highScore = CongestionScorer.score(highCongestion, levels).orElseThrow();

        assertTrue(lowScore < highScore);
        assertEquals(30.0, lowScore);
        assertEquals(80.0, highScore);
    }

    @Test
    @DisplayName("여러 SUBWAY leg는 소요시간 가중 평균으로 계산한다")
    void 다중구간_가중평균() {
        List<RouteLegResponse> legs = List.of(
                subwayLeg("L1", 10.0), // 혼잡도 20, 10분
                subwayLeg("L2", 30.0)); // 혼잡도 60, 30분
        Map<String, Double> levels = Map.of("L1", 20.0, "L2", 60.0);

        double score = CongestionScorer.score(legs, levels).orElseThrow();

        // (20*10 + 60*30) / (10+30) = (200+1800)/40 = 50
        assertEquals(50.0, score, 1e-9);
    }

    @Test
    @DisplayName("혼잡도를 아는 SUBWAY leg가 하나도 없으면 빈 값이다(값을 지어내지 않음)")
    void 데이터없음_빈값() {
        List<RouteLegResponse> legs = List.of(subwayLeg("L1", 10.0), walkLeg(5.0));
        Map<String, Double> levels = Map.of(); // 노선 혼잡도 자체가 없음

        Optional<Double> score = CongestionScorer.score(legs, levels);

        assertTrue(score.isEmpty());
    }

    @Test
    @DisplayName("모르는 노선은 0으로 채우지 않고 계산에서 제외한다")
    void 모르는노선_제외() {
        List<RouteLegResponse> legs = List.of(
                subwayLeg("L1", 10.0), // 혼잡도 앎
                subwayLeg("UNKNOWN", 100.0)); // 혼잡도 모름 — 100분짜리라도 점수에 안 섞인다
        Map<String, Double> levels = Map.of("L1", 40.0);

        double score = CongestionScorer.score(legs, levels).orElseThrow();

        assertEquals(40.0, score, 1e-9);
    }

    @Test
    @DisplayName("BUS·WALK 등 SUBWAY가 아닌 leg는 계산에서 제외한다")
    void SUBWAY_아닌_leg_제외() {
        List<RouteLegResponse> legs = List.of(subwayLeg("L1", 10.0), walkLeg(999.0));
        Map<String, Double> levels = Map.of("L1", 40.0);

        double score = CongestionScorer.score(legs, levels).orElseThrow();

        assertEquals(40.0, score, 1e-9);
    }

    private RouteLegResponse subwayLeg(String routeId, double minutes) {
        return new RouteLegResponse(
                TravelMode.SUBWAY, "A", "에이역", 37.5, 127.0, "B", "비역", 37.51, 127.01,
                routeId, minutes, null, "unavailable", null, null);
    }

    private RouteLegResponse walkLeg(double minutes) {
        return new RouteLegResponse(
                TravelMode.WALK, "A", "에이역", 37.5, 127.0, "B", "비역", 37.51, 127.01,
                "WALK", minutes, null, "unavailable", null, null);
    }
}
