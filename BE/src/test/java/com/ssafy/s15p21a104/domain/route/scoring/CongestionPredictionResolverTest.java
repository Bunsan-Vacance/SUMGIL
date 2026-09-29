package com.ssafy.s15p21a104.domain.route.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;

import com.ssafy.s15p21a104.domain.route.dto.response.CongestionDataStatus;
import com.ssafy.s15p21a104.domain.route.dto.response.CongestionGrade;
import com.ssafy.s15p21a104.domain.route.dto.response.CongestionPrediction;
import com.ssafy.s15p21a104.domain.route.dto.response.PredictionBasis;
import com.ssafy.s15p21a104.domain.route.dto.response.WorstSegmentResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.time.LocalDate;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-236 혼잡 예측 판정 RED (FE-BE 통합 계약 §2).
 *
 * <p>2026-09-22 표시 기준 변경 — 값은 "가장 혼잡한 구간"의 최대이고, 그 구간 위치를 함께
 * 내려준다. 근거(basis)는 호출부가 정한 값을 그대로 쓴다.
 */
class CongestionPredictionResolverTest {

    private static final LocalDate TODAY = LocalDate.of(2026, 9, 21);

    private static final WorstSegmentResponse SEGMENT = new WorstSegmentResponse(
            TravelMode.SUBWAY, "221", "역삼", "222", "강남", 66.3);

    private CongestionPrediction resolve(Double percent, PredictionBasis basis, boolean truncated, LocalDate dep) {
        Optional<CongestionPredictionResolver.Worst> worst = percent == null
                ? Optional.empty()
                : Optional.of(new CongestionPredictionResolver.Worst(percent, basis, SEGMENT));
        return CongestionPredictionResolver.resolve(worst, truncated, dep, TODAY);
    }

    @Test
    @DisplayName("236-P1: 등급 경계는 50·100이다")
    void p1_등급경계() {
        assertEquals(CongestionGrade.LOW, resolve(49.9, PredictionBasis.RECENT_7D, false, TODAY).congestionGrade());
        assertEquals(CongestionGrade.MEDIUM, resolve(50.0, PredictionBasis.RECENT_7D, false, TODAY).congestionGrade());
        assertEquals(CongestionGrade.MEDIUM, resolve(99.9, PredictionBasis.RECENT_7D, false, TODAY).congestionGrade());
        assertEquals(CongestionGrade.HIGH, resolve(100.0, PredictionBasis.RECENT_7D, false, TODAY).congestionGrade());
        assertEquals(CongestionGrade.HIGH, resolve(144.6, PredictionBasis.RECENT_7D, false, TODAY).congestionGrade());
    }

    @Test
    @DisplayName("236-P2: AVAILABLE이면 수치·등급·근거·최악 구간이 있다")
    void p2_available완전() {
        CongestionPrediction link =
                resolve(66.3, PredictionBasis.RECENT_7D, false, TODAY.plusDays(1));
        assertEquals(66.3, link.congestionPercent());
        assertEquals(CongestionGrade.MEDIUM, link.congestionGrade());
        assertEquals(CongestionDataStatus.AVAILABLE, link.dataStatus());
        assertEquals(PredictionBasis.RECENT_7D, link.predictionBasis());
        assertSame(SEGMENT, link.worstSegment());

        CongestionPrediction line = resolve(30.0, PredictionBasis.WEEKDAY_AVERAGE, false, TODAY);
        assertEquals(30.0, line.congestionPercent());
        assertEquals(PredictionBasis.WEEKDAY_AVERAGE, line.predictionBasis());
    }

    @Test
    @DisplayName("236-P3: 비AVAILABLE은 수치·등급·근거·최악 구간이 전부 null이다")
    void p3_비available은null() {
        CongestionPrediction truncated = resolve(null, null, true, TODAY);
        assertEquals(CongestionDataStatus.LINE1_TRUNCATED, truncated.dataStatus());
        assertNull(truncated.congestionPercent());
        assertNull(truncated.congestionGrade());
        assertNull(truncated.predictionBasis());
        assertNull(truncated.worstSegment());

        CongestionPrediction missing = resolve(null, null, false, TODAY);
        assertEquals(CongestionDataStatus.NO_LOOKUP, missing.dataStatus());
        assertNull(missing.congestionPercent());
        assertNull(missing.worstSegment());

        CongestionPrediction future = resolve(66.3, PredictionBasis.RECENT_7D, false, TODAY.plusDays(4));
        assertEquals(CongestionDataStatus.NO_CALIBRATION, future.dataStatus());
        assertNull(future.congestionPercent());

        CongestionPrediction past = resolve(66.3, PredictionBasis.RECENT_7D, false, TODAY.minusDays(1));
        assertEquals(CongestionDataStatus.NO_CALIBRATION, past.dataStatus());
    }

    @Test
    @DisplayName("236-P4: 근거(basis)는 호출부가 정한 값을 그대로 내보낸다 — LIVE 포함")
    void p4_근거_그대로() {
        CongestionPrediction bus = resolve(130.0, PredictionBasis.LIVE, false, TODAY);

        assertEquals(130.0, bus.congestionPercent());
        assertEquals(PredictionBasis.LIVE, bus.predictionBasis());
        assertEquals(CongestionGrade.HIGH, bus.congestionGrade());
    }
}
