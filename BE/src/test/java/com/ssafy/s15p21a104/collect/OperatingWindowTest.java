package com.ssafy.s15p21a104.collect;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.LocalTime;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class OperatingWindowTest {

    @Test
    @DisplayName("시작은 포함, 종료는 미포함")
    void 시작_포함_종료_미포함() {
        OperatingWindow w = OperatingWindow.parse("07:30-13:00");

        assertTrue(w.contains(LocalTime.of(7, 30)));
        assertTrue(w.contains(LocalTime.of(12, 59, 59)));
        assertFalse(w.contains(LocalTime.of(13, 0)));
        assertFalse(w.contains(LocalTime.of(7, 29, 59)));
        assertEquals(330, w.minutesPerDay());
    }

    @Test
    void 자정을_넘는_창() {
        OperatingWindow w = OperatingWindow.parse("22:00-06:00");

        assertTrue(w.contains(LocalTime.of(23, 0)));
        assertTrue(w.contains(LocalTime.of(0, 0)));
        assertTrue(w.contains(LocalTime.of(5, 59)));
        assertFalse(w.contains(LocalTime.of(6, 0)));
        assertFalse(w.contains(LocalTime.of(12, 0)));
        assertEquals(480, w.minutesPerDay());
    }

    @Test
    void 하루_종일_창은_항상_열려_있다() {
        OperatingWindow w = OperatingWindow.parse("00:00-24:00");

        assertTrue(w.isAllDay());
        assertTrue(w.contains(LocalTime.MIDNIGHT));
        assertTrue(w.contains(LocalTime.of(23, 59, 59)));
        assertEquals(1440, w.minutesPerDay());
        assertEquals("00:00-24:00", w.toString());
    }

    @Test
    void 종료가_24시면_자정_직전까지() {
        OperatingWindow w = OperatingWindow.parse("18:00-24:00");

        assertTrue(w.contains(LocalTime.of(23, 59)));
        assertFalse(w.contains(LocalTime.MIDNIGHT));
        assertEquals(360, w.minutesPerDay());
        assertEquals("18:00-24:00", w.toString());
    }

    @Test
    void 빈_값은_하루_종일() {
        assertTrue(OperatingWindow.parse("").isAllDay());
        assertTrue(OperatingWindow.parse(null).isAllDay());
    }

    @Test
    void 형식이_틀리면_기동_시_실패한다() {
        assertThrows(IllegalArgumentException.class, () -> OperatingWindow.parse("0730-1300"));
        assertThrows(IllegalArgumentException.class, () -> OperatingWindow.parse("07:30"));
        assertThrows(IllegalArgumentException.class, () -> OperatingWindow.parse("25:00-26:00"));
    }
}
