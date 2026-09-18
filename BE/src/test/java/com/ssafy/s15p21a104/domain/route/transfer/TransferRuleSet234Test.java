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

    @Test
    @DisplayName("234-T14: BUS 연속은 누적 교집합을 유지하고 소진 시 현재 노선으로 재설정한다")
    void t14_BUS누적교집합_유지와재설정() {
        Set<String> kept = TransferRule.keptTransitLines(
                Set.of(), TravelMode.BUS, Set.of("108"));
        assertEquals(Set.of("108"), kept);

        kept = TransferRule.keptTransitLines(
                kept, TravelMode.BUS, Set.of("108", "143"));
        assertEquals(Set.of("108"), kept);

        TransferRule.TransferDecision decision = TransferRule.decideLines(
                kept, TravelMode.BUS, Set.of("108", "143"),
                TravelMode.BUS, Set.of("143"));
        assertTrue(decision.transfer());

        kept = TransferRule.keptTransitLines(
                kept, TravelMode.BUS, Set.of("143"));
        assertEquals(Set.of("143"), kept);
    }

    @Test
    @DisplayName("234-T15: 다중 BUS와 BIKE 직접 경계는 양방향 모두 환승이다")
    void t15_다중BUS_BIKE직접경계_양방향환승() {
        TransferRule.TransferDecision busToBike = TransferRule.decideLines(
                Set.of("108"), TravelMode.BUS, Set.of("108", "143"),
                TravelMode.BIKE, Set.of("BIKE"));
        TransferRule.TransferDecision bikeToBus = TransferRule.decideLines(
                Set.of(), TravelMode.BIKE, Set.of("BIKE"),
                TravelMode.BUS, Set.of("108", "143"));

        assertTrue(busToBike.transfer());
        assertTrue(bikeToBus.transfer());
    }
}
