package com.ssafy.s15p21a104.domain.buscongestion;

import java.time.Clock;
import java.time.Duration;
import java.time.LocalDateTime;

/**
 * 실시간 혼잡도를 붙여도 되는 검색인지 판정한다 (S15P21A104-297).
 *
 * <p>원천이 "지금 그 정류소로 오는 버스" 라 <b>미래 시각 검색에는 의미가 없다.</b> 두 시간 뒤
 * 출발로 검색한 사용자에게 현재 혼잡도를 보여주면 틀린 정보다. 그래서 출발 시각이 없거나(=지금)
 * 현재에서 창 안일 때만 붙인다.
 *
 * <p>창을 0으로 두면 시각을 준 검색에는 전혀 붙지 않는다 — 설정으로 기능을 좁히는 손잡이다.
 */
public final class BusCongestionWindow {

    private BusCongestionWindow() {
    }

    /**
     * @param departureTime 요청한 출발 시각. null 이면 지금 출발이다
     * @param clock         현재 시각
     * @param window        현재로부터 허용하는 앞뒤 폭(경계 포함)
     * @return 실시간 값을 붙여도 되면 true
     */
    public static boolean isLive(LocalDateTime departureTime, Clock clock, Duration window) {
        if (departureTime == null) {
            return true;
        }
        if (window == null || window.isNegative()) {
            return false;
        }
        Duration gap = Duration.between(LocalDateTime.now(clock), departureTime).abs();
        return gap.compareTo(window) <= 0;
    }
}
