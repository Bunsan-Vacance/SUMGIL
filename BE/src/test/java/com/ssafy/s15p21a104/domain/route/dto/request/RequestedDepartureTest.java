package com.ssafy.s15p21a104.domain.route.dto.request;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.buscongestion.BusCongestionWindow;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 출발 시각을 생략한 요청의 "지금" 을 정한다 (S15P21A104-306).
 *
 * <p>요청의 {@code departureTime} 은 서울 벽시계다. 생략됐을 때 채워 넣는 "지금" 도 같은 기준이어야
 * 한다 — 서버 JVM 시간대(prod 는 UTC)를 따라가면 슬롯·혼잡도 판정이 9시간 어긋난다.
 */
class RequestedDepartureTest {

    /** 서울 09:45 를 UTC 시계로 본 것. prod 컨테이너의 시계가 이 모양이다. */
    private static final Clock UTC_CLOCK =
            Clock.fixed(Instant.parse("2026-09-21T09:45:00+09:00"), ZoneOffset.UTC);

    @Test
    @DisplayName("306-R1: 시각을 주면 그대로 쓴다")
    void r1_준_시각() {
        LocalDateTime given = LocalDateTime.parse("2026-09-21T11:30:00");
        assertEquals(given, RequestedDeparture.resolve(given, UTC_CLOCK));
    }

    @Test
    @DisplayName("306-R2: 시각이 없으면 서버가 UTC 여도 서울 벽시계를 채운다")
    void r2_생략_UTC시계() {
        assertEquals(LocalDateTime.parse("2026-09-21T09:45:00"),
                RequestedDeparture.resolve(null, UTC_CLOCK));
    }

    @Test
    @DisplayName("306-R3: 시각 미지정 검색은 서버 시간대와 무관하게 실시간 창 안이다 — 회귀 고정")
    void r3_실시간_창_안() {
        LocalDateTime now = RequestedDeparture.resolve(null, UTC_CLOCK);
        assertTrue(BusCongestionWindow.isLive(now, UTC_CLOCK, Duration.ofMinutes(10)),
                "시각을 생략한 검색은 '지금 출발' 이라 실시간 혼잡도가 붙어야 한다");
    }
}
