package com.ssafy.s15p21a104.domain.route.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.ssafy.s15p21a104.domain.route.dto.response.CongestionDataStatus;
import com.ssafy.s15p21a104.domain.route.dto.response.CongestionGrade;
import com.ssafy.s15p21a104.domain.route.dto.response.CongestionPrediction;
import com.ssafy.s15p21a104.domain.route.dto.response.PredictionBasis;
import java.time.LocalDate;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-236 혼잡 예측 판정 RED (FE-BE 통합 계약 §2).
 */
class CongestionPredictionResolverTest {

    private static final LocalDate TODAY = LocalDate.of(2026, 9, 21);

    private CongestionPrediction resolve(Double link, Double line, boolean truncated, LocalDate dep) {
        return CongestionPredictionResolver.resolve(
                Optional.ofNullable(link), Optional.ofNullable(line), truncated, dep, TODAY);
    }

    @Test
    @DisplayName("236-P1: 등급 경계는 50·100이다")
    void p1_등급경계() {
        assertEquals(CongestionGrade.LOW, resolve(49.9, null, false, TODAY).congestionGrade());
        assertEquals(CongestionGrade.MEDIUM, resolve(50.0, null, false, TODAY).congestionGrade());
        assertEquals(CongestionGrade.MEDIUM, resolve(99.9, null, false, TODAY).congestionGrade());
        assertEquals(CongestionGrade.HIGH, resolve(100.0, null, false, TODAY).congestionGrade());
        assertEquals(CongestionGrade.HIGH, resolve(144.6, null, false, TODAY).congestionGrade());
    }

    @Test
    @DisplayName("236-P2: AVAILABLE이면 수치·등급·근거가 있다")
    void p2_available완전() {
        CongestionPrediction link =
                resolve(66.3, 80.0, false, TODAY.plusDays(1));
        assertEquals(66.3, link.congestionPercent());
        assertEquals(CongestionGrade.MEDIUM, link.congestionGrade());
        assertEquals(CongestionDataStatus.AVAILABLE, link.dataStatus());
        assertEquals(PredictionBasis.RECENT_7D, link.predictionBasis());

        CongestionPrediction line = resolve(null, 30.0, false, TODAY);
        assertEquals(30.0, line.congestionPercent());
        assertEquals(PredictionBasis.WEEKDAY_AVERAGE, line.predictionBasis());
    }

    @Test
    @DisplayName("236-P3: 비AVAILABLE은 수치·등급·근거가 전부 null이다")
    void p3_비available은null() {
        CongestionPrediction truncated = resolve(null, null, true, TODAY);
        assertEquals(CongestionDataStatus.LINE1_TRUNCATED, truncated.dataStatus());
        assertNull(truncated.congestionPercent());
        assertNull(truncated.congestionGrade());
        assertNull(truncated.predictionBasis());

        CongestionPrediction missing = resolve(null, null, false, TODAY);
        assertEquals(CongestionDataStatus.NO_LOOKUP, missing.dataStatus());
        assertNull(missing.congestionPercent());

        CongestionPrediction future = resolve(66.3, null, false, TODAY.plusDays(4));
        assertEquals(CongestionDataStatus.NO_CALIBRATION, future.dataStatus());
        assertNull(future.congestionPercent());

        CongestionPrediction past = resolve(66.3, null, false, TODAY.minusDays(1));
        assertEquals(CongestionDataStatus.NO_CALIBRATION, past.dataStatus());
    }

    @Test
    @DisplayName("236-P4: 링크 점수가 노선 점수보다 우선한다")
    void p4_링크우선() {
        CongestionPrediction resolved = resolve(66.3, 30.0, false, TODAY);

        assertEquals(66.3, resolved.congestionPercent());
        assertEquals(PredictionBasis.RECENT_7D, resolved.predictionBasis());
    }
}
