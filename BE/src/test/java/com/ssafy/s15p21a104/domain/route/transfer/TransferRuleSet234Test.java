package com.ssafy.s15p21a104.domain.route.transfer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class TransferRuleSet234Test {

    private final TransferRule rule = new TransferRule(180).withTable(Map.of(
            new TransferRule.TransferKey("B", "108", "1002"), 200,
            new TransferRule.TransferKey("B", "143", "1002"), 300));

    @Test
    @DisplayName("234-T10: 공통 노선 있으면 환승 아님")
    void t10_공통노선_비환승() {
        TransferRule.TransferDecision d = TransferRule.decideLines(
                Set.of("108"), TravelMode.BUS, Set.of("108", "143"),
                TravelMode.BUS, Set.of("108", "143"));

        assertEquals(new TransferRule.TransferDecision(false, null), d);
    }

    @Test
    @DisplayName("234-T11: 공통 노선 없으면 환승 (108→143 같은 정류장 포함)")
    void t11_교집합없음_환승() {
        TransferRule.TransferDecision d = TransferRule.decideLines(
                Set.of("108"), TravelMode.BUS, Set.of("108"),
                TravelMode.BUS, Set.of("143"));

        assertTrue(d.transfer());
    }

    @Test
    @DisplayName("234-T12: 경계 비용은 후보 쌍 최소값")
    void t12_경계비용_최소값() {
        assertEquals(200, rule.transferCost("B", Set.of("108", "143"), Set.of("1002")));
        assertEquals(180, rule.transferCost("B", Set.of("999"), Set.of("1002")));
        assertEquals(180, rule.transferCost("B", Set.of(), Set.of("1002")));
    }

    @Test
    @DisplayName("234-T13: 첫 탑승(kept 비어 있음)은 환승 아님")
    void t13_첫탑승_비환승() {
        TransferRule.TransferDecision d = TransferRule.decideLines(
                Set.of(), TravelMode.WALK, Set.of(), TravelMode.SUBWAY, Set.of("1002"));

        assertEquals(new TransferRule.TransferDecision(false, null), d);
    }
}
