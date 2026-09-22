package com.ssafy.s15p21a104.domain.route.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.congestion.scoring.CongestionScorer;
import com.ssafy.s15p21a104.domain.congestion.scoring.LinkCongestionScorer;
import com.ssafy.s15p21a104.domain.route.dto.response.PredictionBasis;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.Optional;
import java.util.function.Function;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 혼잡 최악값 선택 테스트(2026-09-22) — 링크 예측·BUS 실시간·노선 통계 중
 * "가장 혼잡한 구간" 하나를 골라 표시 계약으로 바꾼다.
 */
class WorstCongestionPickerTest {

    private static final Function<String, String> NAMES = id -> switch (id) {
        case "221" -> "역삼";
        case "222" -> "강남";
        default -> id;
    };

    private static RouteLegResponse subwayLeg(String routeId) {
        return new RouteLegResponse(TravelMode.SUBWAY, "222", "강남", 37.49, 127.02,
                "D016", "성복", 37.31, 127.08, routeId, 29.0, null, "unavailable", null, null, null);
    }

    private static RouteLegResponse busLeg() {
        return new RouteLegResponse(TravelMode.BUS, "S1", "정류장1", 37.5, 127.0,
                "S2", "정류장2", 37.51, 127.01, "B1", 20.0, null, "unavailable", null, null, null);
    }

    @Test
    @DisplayName("W1: 링크 최악이 있으면 RECENT_7D + 지하철 구간 위치를 돌려준다")
    void w1_링크() {
        LinkCongestionScorer.Result link = new LinkCongestionScorer.Result(
                new Edge("221", "222", "1002", 180, 60, TravelMode.SUBWAY), 98.0);

        CongestionPredictionResolver.Worst pick = WorstCongestionPicker.pick(
                Optional.of(link), NAMES, Optional.empty(), Optional.empty()).orElseThrow();

        assertEquals(98.0, pick.percent(), 1e-9);
        assertEquals(PredictionBasis.RECENT_7D, pick.basis());
        assertEquals(TravelMode.SUBWAY, pick.segment().mode());
        assertEquals("221", pick.segment().fromNodeId());
        assertEquals("역삼", pick.segment().fromNodeName());
        assertEquals("강남", pick.segment().toNodeName());
        assertEquals(98.0, pick.segment().congestionPercent(), 1e-9);
    }

    @Test
    @DisplayName("W2: 버스 실시간이 지하철 링크보다 혼잡하면 LIVE + 버스 구간 위치를 돌려준다")
    void w2_버스가_더_혼잡() {
        LinkCongestionScorer.Result link = new LinkCongestionScorer.Result(
                new Edge("221", "222", "1002", 180, 60, TravelMode.SUBWAY), 98.0);

        CongestionPredictionResolver.Worst pick = WorstCongestionPicker.pick(
                Optional.of(link), NAMES, Optional.of(new CongestionScorer.Worst(130.0, busLeg())),
                Optional.empty()).orElseThrow();

        assertEquals(130.0, pick.percent(), 1e-9);
        assertEquals(PredictionBasis.LIVE, pick.basis());
        assertEquals(TravelMode.BUS, pick.segment().mode());
        assertEquals("정류장1", pick.segment().fromNodeName());
        assertEquals("정류장2", pick.segment().toNodeName());
    }

    @Test
    @DisplayName("W3: 동률이면 지하철 링크가 이긴다(RECENT_7D 유지)")
    void w3_동률_링크우선() {
        LinkCongestionScorer.Result link = new LinkCongestionScorer.Result(
                new Edge("221", "222", "1002", 180, 60, TravelMode.SUBWAY), 98.0);

        CongestionPredictionResolver.Worst pick = WorstCongestionPicker.pick(
                Optional.of(link), NAMES, Optional.of(new CongestionScorer.Worst(98.0, busLeg())),
                Optional.empty()).orElseThrow();

        assertEquals(PredictionBasis.RECENT_7D, pick.basis());
        assertEquals(TravelMode.SUBWAY, pick.segment().mode());
    }

    @Test
    @DisplayName("W4: 링크가 없고 버스만 알면 LIVE")
    void w4_버스만() {
        CongestionPredictionResolver.Worst pick = WorstCongestionPicker.pick(
                Optional.empty(), NAMES, Optional.of(new CongestionScorer.Worst(70.0, busLeg())),
                Optional.empty()).orElseThrow();

        assertEquals(70.0, pick.percent(), 1e-9);
        assertEquals(PredictionBasis.LIVE, pick.basis());
        assertEquals(TravelMode.BUS, pick.segment().mode());
    }

    @Test
    @DisplayName("W5: 링크·버스가 없으면 노선 통계 최악을 WEEKDAY_AVERAGE로 쓴다")
    void w5_노선통계_폴백() {
        RouteLegResponse leg = subwayLeg("1077");

        CongestionPredictionResolver.Worst pick = WorstCongestionPicker.pick(
                Optional.empty(), NAMES, Optional.empty(),
                Optional.of(new CongestionScorer.Worst(89.8, leg))).orElseThrow();

        assertEquals(89.8, pick.percent(), 1e-9);
        assertEquals(PredictionBasis.WEEKDAY_AVERAGE, pick.basis());
        assertEquals(TravelMode.SUBWAY, pick.segment().mode());
        assertEquals("강남", pick.segment().fromNodeName());
        assertEquals("성복", pick.segment().toNodeName());
    }

    @Test
    @DisplayName("W6: 아는 값이 하나도 없으면 빈 값(값을 지어내지 않음)")
    void w6_없음() {
        Optional<CongestionPredictionResolver.Worst> pick = WorstCongestionPicker.pick(
                Optional.empty(), NAMES, Optional.empty(), Optional.empty());

        assertTrue(pick.isEmpty());
    }
}
