package com.ssafy.s15p21a104.domain.buscongestion;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 실시간 혼잡도를 붙일 검색인지 판정 (S15P21A104-297).
 *
 * <p>원천이 "지금 오는 버스" 라 미래 시각 검색에 붙이면 틀린 정보다. 두 시간 뒤 출발로 검색한
 * 사용자에게 현재 혼잡도를 보여주면 안 된다.
 */
class BusCongestionWindowTest {

    private static final Clock FIXED =
            Clock.fixed(Instant.parse("2026-09-21T09:45:00+09:00"), ZoneOffset.of("+09:00"));
    private static final Duration WINDOW = Duration.ofMinutes(10);

    private static LocalDateTime at(String time) {
        return LocalDateTime.parse("2026-09-21T" + time);
    }

    @Test
    @DisplayName("297-W1: 출발 시각을 안 주면 지금 출발이다")
    void w1_시각_없음() {
        assertTrue(BusCongestionWindow.isLive(null, FIXED, WINDOW));
    }

    @Test
    @DisplayName("297-W2: 현재 시각 그대로면 붙인다")
    void w2_현재() {
        assertTrue(BusCongestionWindow.isLive(at("09:45:00"), FIXED, WINDOW));
    }

    @Test
    @DisplayName("297-W3: 창 안(±9분)이면 붙인다")
    void w3_창_안() {
        assertTrue(BusCongestionWindow.isLive(at("09:54:00"), FIXED, WINDOW), "9분 뒤");
        assertTrue(BusCongestionWindow.isLive(at("09:36:00"), FIXED, WINDOW), "9분 전");
    }

    @Test
    @DisplayName("297-W4: 창 밖(+11분)이면 안 붙인다 — 미래 검색에 현재 값을 보여주지 않는다")
    void w4_미래() {
        assertFalse(BusCongestionWindow.isLive(at("09:56:00"), FIXED, WINDOW), "11분 뒤");
        assertFalse(BusCongestionWindow.isLive(at("11:45:00"), FIXED, WINDOW), "2시간 뒤");
    }

    @Test
    @DisplayName("297-W5: 창 밖(-11분)인 과거도 안 붙인다")
    void w5_과거() {
        assertFalse(BusCongestionWindow.isLive(at("09:34:00"), FIXED, WINDOW));
    }

    @Test
    @DisplayName("297-W6: 경계는 포함이다 (정확히 ±10분)")
    void w6_경계() {
        assertTrue(BusCongestionWindow.isLive(at("09:55:00"), FIXED, WINDOW));
        assertTrue(BusCongestionWindow.isLive(at("09:35:00"), FIXED, WINDOW));
    }

    @Test
    @DisplayName("297-W7: 창이 0이거나 음수면 시각을 준 검색엔 안 붙인다 — 설정으로 끌 수 있다")
    void w7_창_0() {
        assertFalse(BusCongestionWindow.isLive(at("09:45:01"), FIXED, Duration.ZERO));
        assertTrue(BusCongestionWindow.isLive(null, FIXED, Duration.ZERO), "시각 없음은 언제나 지금");
    }
}
