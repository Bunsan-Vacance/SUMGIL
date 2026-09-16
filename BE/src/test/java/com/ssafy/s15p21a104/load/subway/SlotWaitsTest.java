package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * wait_sec 정의: 슬롯 안 임의 시각에 승강장에 도착했을 때 다음 열차 출발까지의 기대 대기(초).
 * 배차가 고르면 배차간격 ÷ 2 와 같고, 열차가 없는 슬롯은 자연히 첫차까지의 대기가 된다.
 * 출발 시각은 운행일 기준 초(자정 넘는 24:30 = 88,200)로 받고 24시간으로 접어 슬롯을 정한다.
 */
class SlotWaitsTest {

    @Test
    @DisplayName("10분 간격이면 모든 슬롯의 기대 대기는 300초 — 배차간격 ÷ 2")
    void regularHeadwayIsHalfInterval() {
        List<Integer> deps = new java.util.ArrayList<>();
        for (int t = 0; t < 86400; t += 600) {
            deps.add(t);
        }

        int[] waits = SlotWaits.expectedWaits(deps);

        assertEquals(48, waits.length);
        for (int w : waits) {
            assertEquals(300, w);
        }
    }

    @Test
    @DisplayName("열차가 없는 슬롯은 첫차까지의 대기 — 첫차 05:00 이면 00:00 슬롯은 17,100초, 04:30 슬롯은 900초")
    void emptySlotWaitsForFirstTrain() {
        int[] waits = SlotWaits.expectedWaits(List.of(18000));

        assertEquals(17100, waits[0]);
        assertEquals(900, waits[9]);
    }

    @Test
    @DisplayName("막차 뒤 슬롯은 다음 날 첫차까지 이어 붙인다 — 첫차 00:10 이면 23:30 슬롯은 1,500초")
    void wrapsAroundMidnight() {
        int[] waits = SlotWaits.expectedWaits(List.of(600, 3600));

        assertEquals(1500, waits[47]);
    }

    @Test
    @DisplayName("슬롯 경계에 걸친 간격도 정확히 적분한다 — 00:25·00:35 출발이면 00:00 슬롯은 700초")
    void integratesAcrossSlotBoundary() {
        int[] waits = SlotWaits.expectedWaits(List.of(1500, 2100));

        assertEquals(700, waits[0]);
    }

    @Test
    @DisplayName("자정 넘는 표기(24:30 = 88,200초)는 00:30 으로 접어 1번 슬롯에 들어간다")
    void foldsAfterMidnightTimes() {
        assertEquals(1800, SlotWaits.clockSeconds(88200));
        assertEquals(1, SlotWaits.slotOf(88200));
        assertEquals(47, SlotWaits.slotOf(86399));

        int[] waits = SlotWaits.expectedWaits(List.of(88200));
        assertEquals(900, waits[0]);
    }

    @Test
    @DisplayName("하루 운행이 없는 요일은 모든 슬롯이 86,400 — 운행 없음 표식이며 값을 만들어 넣지 않는다")
    void noServiceDayIsMarked() {
        int[] waits = SlotWaits.expectedWaits(List.of());

        for (int w : waits) {
            assertEquals(SlotWaits.NO_SERVICE, w);
        }
    }

    @Test
    @DisplayName("요일별 출발 목록으로 3×48 표를 만들고 (dow, slot) 로 읽는다")
    void buildsFromDeparturesByDow() {
        SlotWaits sw = SlotWaits.fromDepartures(List.of(List.of(18000), List.of(), List.of(600, 3600)));

        assertEquals(17100, sw.wait(0, 0));
        assertEquals(SlotWaits.NO_SERVICE, sw.wait(1, 10));
        assertEquals(1500, sw.wait(2, 47));
    }

    @Test
    @DisplayName("범위 밖 값(음수, 86,400 초과)이나 3×48 이 아닌 표는 만들 수 없다")
    void rejectsInvalidTables() {
        int[][] bad = new int[3][48];
        bad[0][0] = -1;
        assertThrows(IllegalArgumentException.class, () -> SlotWaits.of(bad));
        assertThrows(IllegalArgumentException.class, () -> SlotWaits.of(new int[2][48]));
    }
}
