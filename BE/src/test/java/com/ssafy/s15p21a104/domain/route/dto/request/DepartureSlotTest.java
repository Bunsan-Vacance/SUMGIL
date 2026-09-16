package com.ssafy.s15p21a104.domain.route.dto.request;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.LocalDateTime;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 요청 시각 -> (dow_type, time_slot) 변환. S15P21A104-63 확장(FE-대기시간-반영-요청.md 4번, API 파라미터).
 */
class DepartureSlotTest {

    @Test
    @DisplayName("평일 낮 12시 -> dow_type 0, time_slot 24")
    void 평일_낮12시() {
        DepartureSlot slot = DepartureSlot.of(LocalDateTime.of(2026, 9, 10, 12, 0)); // 목요일

        assertEquals(0, slot.dowType());
        assertEquals(24, slot.timeSlot());
    }

    @Test
    @DisplayName("토요일은 dow_type 1")
    void 토요일() {
        DepartureSlot slot = DepartureSlot.of(LocalDateTime.of(2026, 9, 12, 9, 0)); // 토요일

        assertEquals(1, slot.dowType());
    }

    @Test
    @DisplayName("일요일은 dow_type 2 (공휴일 캘린더 없어 당장은 일요일만)")
    void 일요일() {
        DepartureSlot slot = DepartureSlot.of(LocalDateTime.of(2026, 9, 13, 9, 0)); // 일요일

        assertEquals(2, slot.dowType());
    }

    @Test
    @DisplayName("자정은 time_slot 0")
    void 자정() {
        DepartureSlot slot = DepartureSlot.of(LocalDateTime.of(2026, 9, 10, 0, 0));

        assertEquals(0, slot.timeSlot());
    }

    @Test
    @DisplayName("30분 단위 뒤쪽 절반은 홀수 슬롯")
    void 삼십분_뒤쪽() {
        DepartureSlot slot = DepartureSlot.of(LocalDateTime.of(2026, 9, 10, 8, 30));

        assertEquals(17, slot.timeSlot());
    }

    @Test
    @DisplayName("23시대는 마지막 슬롯 46·47")
    void 마지막_슬롯() {
        assertEquals(46, DepartureSlot.of(LocalDateTime.of(2026, 9, 10, 23, 0)).timeSlot());
        assertEquals(47, DepartureSlot.of(LocalDateTime.of(2026, 9, 10, 23, 30)).timeSlot());
    }
}
