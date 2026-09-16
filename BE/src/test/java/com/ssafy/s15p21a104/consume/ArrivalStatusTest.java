package com.ssafy.s15p21a104.consume;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.ssafy.s15p21a104.collect.OperatingWindow;
import java.time.Duration;
import java.time.OffsetDateTime;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * subway:arrival:status 의 state 판정 (S15P21A104-171).
 *
 * <p>192(전우석)가 "정보 없음 / TTL 만료 / 운영창 밖 / 수집 장애" 를 구분해야 하는데, 역별 키의 부재만으로는 못 가른다.
 * 역별 키가 없을 때 이 상태 키를 함께 보면 갈린다.
 */
class ArrivalStatusTest {

    private static final OperatingWindow WINDOW = OperatingWindow.parse("10:00-15:30");
    private static final Duration STALE_AFTER = Duration.ofMinutes(3);

    private static OffsetDateTime at(String kst) {
        return OffsetDateTime.parse(kst);
    }

    @Test
    @DisplayName("창 안이고 최근 회차가 있으면 ok")
    void 정상() {
        assertEquals(ArrivalStatus.State.OK,
                ArrivalStatus.evaluate(at("2026-09-16T10:31:30+09:00"), WINDOW, at("2026-09-16T10:31:00+09:00"), STALE_AFTER));
    }

    @Test
    @DisplayName("창 밖이면 outside_window — 장애가 아니라 정상 상태다")
    void 창_밖() {
        assertEquals(ArrivalStatus.State.OUTSIDE_WINDOW,
                ArrivalStatus.evaluate(at("2026-09-16T16:00:00+09:00"), WINDOW, at("2026-09-16T15:29:00+09:00"), STALE_AFTER));
        assertEquals(ArrivalStatus.State.OUTSIDE_WINDOW,
                ArrivalStatus.evaluate(at("2026-09-16T09:00:00+09:00"), WINDOW, null, STALE_AFTER));
    }

    @Test
    @DisplayName("창 안인데 회차가 3분 넘게 안 오면 stale")
    void 수집_지연() {
        assertEquals(ArrivalStatus.State.STALE,
                ArrivalStatus.evaluate(at("2026-09-16T10:35:00+09:00"), WINDOW, at("2026-09-16T10:31:00+09:00"), STALE_AFTER));
    }

    @Test
    @DisplayName("창 안인데 회차가 아직 하나도 없으면 stale — ok 라고 하면 안 된다")
    void 창_안인데_회차_없음() {
        assertEquals(ArrivalStatus.State.STALE,
                ArrivalStatus.evaluate(at("2026-09-16T10:31:00+09:00"), WINDOW, null, STALE_AFTER));
    }

    @Test
    @DisplayName("경계 — 정확히 3분이면 아직 ok, 넘으면 stale")
    void 경계() {
        assertEquals(ArrivalStatus.State.OK,
                ArrivalStatus.evaluate(at("2026-09-16T10:34:00+09:00"), WINDOW, at("2026-09-16T10:31:00+09:00"), STALE_AFTER));
        assertEquals(ArrivalStatus.State.STALE,
                ArrivalStatus.evaluate(at("2026-09-16T10:34:01+09:00"), WINDOW, at("2026-09-16T10:31:00+09:00"), STALE_AFTER));
    }

    @Test
    @DisplayName("Redis 에 쓰는 모양 — state 는 소문자 문자열, window 도 함께 준다")
    void 값_모양() {
        var value = ArrivalStatus.value(ArrivalStatus.State.OUTSIDE_WINDOW, at("2026-09-16T15:29:00+09:00"),
                WINDOW, at("2026-09-16T16:00:00+09:00"));

        assertEquals("outside_window", value.get("state"));
        assertEquals("2026-09-16T15:29:00+09:00", value.get("last_poll_run_at"));
        assertEquals("10:00-15:30", value.get("window"));
        assertEquals("2026-09-16T16:00:00+09:00", value.get("updated_at"));
    }

    @Test
    @DisplayName("회차가 하나도 없으면 last_poll_run_at 은 null 로 나간다 — 0 이나 빈 문자열로 속이지 않는다")
    void 회차_없을_때_값() {
        var value = ArrivalStatus.value(ArrivalStatus.State.STALE, null, WINDOW, at("2026-09-16T10:31:00+09:00"));

        assertEquals("stale", value.get("state"));
        assertEquals(null, value.get("last_poll_run_at"));
    }
}
