package com.ssafy.s15p21a104.domain.route.transfer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-96 환승 상수 규칙 단위 테스트. 순수 값 기반이라 DB·Redis가 필요 없다.
 */
class TransferRuleTest {

    @Test
    @DisplayName("96-T1 노선 전환 1회면 travelSec + 180 (AC1)")
    void t1_노선전환_1회_상수1회부가() {
        TransferRule rule = new TransferRule(180);

        assertTrue(rule.isTransfer("1002", "1005"));
        assertEquals(280, rule.cost(100, "1002", "1005"));
    }

    @Test
    @DisplayName("96-T2 노선 전환 N회면 상수 x N (AC1)")
    void t2_노선전환_N회_상수N회부가() {
        TransferRule rule = new TransferRule(180);

        // 3구간 연속 환승: 100 + 200 + 150 이동 + 180 * 3 환승
        long total = rule.cost(100, "1002", "1005")
                + rule.cost(200, "1005", "1008")
                + rule.cost(150, "1008", "1002");

        assertEquals(100 + 200 + 150 + 180 * 3, total);
    }

    @Test
    @DisplayName("96-T3 같은 노선이면 travelSec 그대로 (AC2)")
    void t3_같은노선_상수없음() {
        TransferRule rule = new TransferRule(180);

        assertFalse(rule.isTransfer("1002", "1002"));
        assertEquals(100, rule.cost(100, "1002", "1002"));
    }

    @Test
    @DisplayName("96-T4 현재 노선 없음(첫 엣지)은 환승 아님 (AC3)")
    void t4_첫엣지_환승아님() {
        TransferRule rule = new TransferRule(180);

        assertFalse(rule.isTransfer(null, "1002"));
        assertEquals(100, rule.cost(100, null, "1002"));

        assertFalse(rule.isTransfer("", "1002"));
        assertEquals(100, rule.cost(100, "", "1002"));
    }

    @Test
    @DisplayName("96-T5 상수 180에서 300으로 교체되면 300이 반영된다 (AC4)")
    void t5_상수변경_300반영() {
        TransferRule changed = new TransferRule(300);

        assertEquals(300, changed.getDefaultSec());
        assertEquals(400, changed.cost(100, "1002", "1005"));
        assertEquals(100, changed.cost(100, "1002", "1002"));
    }
}
