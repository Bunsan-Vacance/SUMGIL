package com.ssafy.s15p21a104.domain.buscongestion;

import java.time.Clock;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.ZoneId;

/**
 * 실시간 혼잡도를 붙여도 되는 검색인지 판정한다 (S15P21A104-297).
 *
 * <p>원천이 "지금 그 정류소로 오는 버스" 라 <b>미래 시각 검색에는 의미가 없다.</b> 두 시간 뒤
 * 출발로 검색한 사용자에게 현재 혼잡도를 보여주면 틀린 정보다. 그래서 출발 시각이 없거나(=지금)
 * 현재에서 창 안일 때만 붙인다.
 *
 * <p>창을 0으로 두면 시각을 준 검색에는 전혀 붙지 않는다 — 설정으로 기능을 좁히는 손잡이다.
 *
 * <p><b>시각은 서울 벽시계로 비교한다 (S15P21A104-306).</b> {@code departureTime} 은 FE 가 보내는
 * 서울 기준 {@code LocalDateTime} 이라 시간대가 없다. 서버 JVM 이 UTC 면(prod 컨테이너가 그렇다)
 * {@code LocalDateTime.now(clock)} 이 9시간 이른 값을 줘서 지금 출발 검색이 통째로 "미래" 로
 * 판정됐다 — 실제 화면에서 버스 등급이 한 번도 안 나온 원인이다. 배포 이미지에도
 * {@code -Duser.timezone=Asia/Seoul} 을 넣지만, 그 설정이 빠져도 이 판정만은 안 깨지게 여기서 못 박는다.
 */
public final class BusCongestionWindow {

    /** {@code departureTime} 이 기준으로 삼는 시간대. 서버 시간대와 무관하게 이 값으로 비교한다. */
    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");

    private BusCongestionWindow() {
    }

    /**
     * @param departureTime 요청한 출발 시각(<b>서울 벽시계</b>). null 이면 지금 출발이다
     * @param clock         현재 시각. 어느 시간대의 시계든 서울 기준으로 환산해 비교한다
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
        Duration gap = Duration.between(LocalDateTime.now(clock.withZone(SEOUL)), departureTime).abs();
        return gap.compareTo(window) <= 0;
    }
}
