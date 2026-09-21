package com.ssafy.s15p21a104.domain.route.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.buscongestion.BusCongestionGrade;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 버스 혼잡 등급 → 공통 수치 축 매핑 테스트(5부 C1).
 * 앵커: 100 = 보통 = 지하철 100(정원)과 같은 "가중 없음" 경계.
 */
class BusCrowdingScaleTest {

    @Test
    @DisplayName("S1: 등급 4종 → 수치 매핑(여유<보통=100<혼잡<혼잡심화)")
    void s1_등급수치() {
        assertEquals(70.0, BusCrowdingScale.levelOf(BusCongestionGrade.RELAXED).orElseThrow(), 0.001);
        assertEquals(100.0, BusCrowdingScale.levelOf(BusCongestionGrade.NORMAL).orElseThrow(), 0.001);
        assertEquals(130.0, BusCrowdingScale.levelOf(BusCongestionGrade.CONGESTED).orElseThrow(), 0.001);
        assertEquals(170.0, BusCrowdingScale.levelOf(BusCongestionGrade.SATURATED).orElseThrow(), 0.001);
    }

    @Test
    @DisplayName("S2: 보통(100)은 가중 경계 — 여유·보통은 가중 없음, 혼잡부터 가중")
    void s2_가중경계() {
        assertFalse(CongestionCostModel.hasWeightEffect(BusCrowdingScale.RELAXED_LEVEL));
        assertFalse(CongestionCostModel.hasWeightEffect(BusCrowdingScale.NORMAL_LEVEL));
        assertTrue(CongestionCostModel.hasWeightEffect(BusCrowdingScale.CONGESTED_LEVEL));
        assertTrue(CongestionCostModel.hasWeightEffect(BusCrowdingScale.SATURATED_LEVEL));
    }

    @Test
    @DisplayName("S3: 문자열 등급(FE 계약값)도 같은 축으로 — 미지·null은 중립")
    void s3_문자열등급() {
        assertEquals(130.0, BusCrowdingScale.levelOfName("CONGESTED").orElseThrow(), 0.001);
        assertTrue(BusCrowdingScale.levelOf(null).isEmpty());
        assertTrue(BusCrowdingScale.levelOfName(null).isEmpty());
        assertTrue(BusCrowdingScale.levelOfName("").isEmpty());
        assertTrue(BusCrowdingScale.levelOfName("UNKNOWN").isEmpty());
    }
}
