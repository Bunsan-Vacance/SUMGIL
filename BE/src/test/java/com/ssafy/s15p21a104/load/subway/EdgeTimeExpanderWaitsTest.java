package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** 슬롯별 대기가 있는 엣지는 그 값을, 없는 엣지(코레일 avg)는 0 을 wait_sec 에 넣는다. */
class EdgeTimeExpanderWaitsTest {

    private final EdgeRow gangnam = new EdgeRow("강남", "역삼", "SUBWAY", "1002", 120, "timetable");
    private final EdgeRow korail = new EdgeRow("관악", "안양", "SUBWAY", "1001", 120, "avg");

    private final Map<String, SlotWaits> waits = Map.of(
            "강남|역삼|1002", SlotWaits.fromDepartures(List.of(List.of(28800, 29400, 30000, 30600), List.of(), List.of())));

    @Test
    @DisplayName("대기 표가 있는 엣지는 (dow, slot) 마다 그 값을 쓴다 — 평일 08:00 슬롯(10분 간격)은 300, 토요일은 86,400")
    void usesSlotWaits() {
        List<EdgeTimeRow> rows = EdgeTimeExpander.expandAll(List.of(gangnam), waits);

        EdgeTimeRow weekday0800 = rows.stream().filter(r -> r.dowType() == 0 && r.timeSlot() == 16).findFirst().orElseThrow();
        EdgeTimeRow saturday = rows.stream().filter(r -> r.dowType() == 1 && r.timeSlot() == 16).findFirst().orElseThrow();
        assertEquals(300, weekday0800.waitSec());
        assertEquals(SlotWaits.NO_SERVICE, saturday.waitSec());
        assertEquals(120, weekday0800.travelSec());
        assertEquals(144, rows.size());
    }

    @Test
    @DisplayName("대기 표가 없는 엣지는 wait_sec 0 으로 144행 복제한다 (기존 동작)")
    void fallsBackToZero() {
        List<EdgeTimeRow> rows = EdgeTimeExpander.expandAll(List.of(korail), waits);

        assertEquals(144, rows.size());
        assertTrue(rows.stream().allMatch(r -> r.waitSec() == 0));
    }
}
