package com.ssafy.s15p21a104.domain.route.transfer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Map;

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

    @Test
    @DisplayName("실측 있으면 역별 시간으로 가산한다")
    void t_실측있으면_실측가산() {
        TransferRule rule = new TransferRule(180).withTable(Map.of(
                new TransferRule.TransferKey("시청", "1001", "1002"), 84));

        assertEquals(184, rule.costWithStation(100, "시청", "1001", "1002"));
    }

    @Test
    @DisplayName("실측 없으면 상수로 폴백한다")
    void t_실측없으면_상수폴백() {
        TransferRule rule = new TransferRule(180).withTable(Map.of(
                new TransferRule.TransferKey("시청", "1001", "1002"), 84));

        assertEquals(280, rule.costWithStation(100, "시청", "1001", "1005"));
        assertEquals(280, rule.costWithStation(100, null, "1001", "1002"));
    }

    @Test
    @DisplayName("같은 노선·첫 엣지는 실측표와 무관하게 가산 없다")
    void t_같은노선_첫엣지_가산없음() {
        TransferRule rule = new TransferRule(180).withTable(Map.of(
                new TransferRule.TransferKey("시청", "1001", "1001"), 999));

        assertEquals(100, rule.costWithStation(100, "시청", "1001", "1001"));
        assertEquals(100, rule.costWithStation(100, null, null, "1002"));
    }

    @Test
    @DisplayName("213-T1: WALK ↔ 주행 경계는 접근이라 환승이 아니다")
    void t213_접근경계_환승아님() {
        assertTrue(TransferRule.isAccessBoundary(TravelMode.WALK, TravelMode.BIKE));
        assertTrue(TransferRule.isAccessBoundary(TravelMode.BIKE, TravelMode.WALK));
        assertTrue(TransferRule.isAccessBoundary(TravelMode.WALK, TravelMode.SUBWAY));
        assertTrue(TransferRule.isAccessBoundary(TravelMode.BUS, TravelMode.WALK));
        assertFalse(TransferRule.isAccessBoundary(TravelMode.SUBWAY, TravelMode.BIKE));
        assertFalse(TransferRule.isAccessBoundary(TravelMode.SUBWAY, TravelMode.SUBWAY));
        assertFalse(TransferRule.isAccessBoundary(null, TravelMode.BIKE));
    }

    @Test
    @DisplayName("213-T1: 접근 경계는 환승 비용을 가산하지 않는다")
    void t213_접근경계_가산없음() {
        TransferRule rule = new TransferRule(180);

        assertEquals(100, rule.costWithStation(
                100, "R1", "WALK", "BIKE", TravelMode.WALK, TravelMode.BIKE));
        assertEquals(280, rule.costWithStation(
                100, "B", "L1", "L2", TravelMode.SUBWAY, TravelMode.SUBWAY));
    }
}
