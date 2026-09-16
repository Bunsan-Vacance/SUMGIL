package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.collect.OperatingWindow;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * {@code subway:arrival:status} 의 상태 판정 (S15P21A104-171).
 *
 * <p>192(실시간 도착 조회 API)는 "정보 없음 / TTL 만료 / 운영창 밖 / 수집 장애" 를 구분해야 하는데,
 * 역별 키가 없다는 사실만으로는 못 가른다. 역별 키의 유무와 이 상태를 함께 보면 갈린다.
 *
 * <table>
 *   <tr><th>역별 키</th><th>state</th><th>읽는 쪽이 보여줄 것</th></tr>
 *   <tr><td>있음</td><td>ok</td><td>실시간 도착 정보</td></tr>
 *   <tr><td>없음</td><td>ok</td><td>그 역에 정보 없음 (열차 없음·미수집 역)</td></tr>
 *   <tr><td>없음</td><td>outside_window</td><td>지금은 실시간 제공 시간이 아님 — 장애가 아니다</td></tr>
 *   <tr><td>없음</td><td>stale</td><td>수집 지연 중</td></tr>
 * </table>
 */
public final class ArrivalStatus {

    /** 창 안인데 이 시간 넘게 회차가 없으면 지연으로 본다. 수집 주기 60초 + 서킷 브레이커 60초보다 넉넉하게. */
    public static final Duration STALE_AFTER = Duration.ofMinutes(3);

    private ArrivalStatus() {
    }

    public enum State {
        OK, OUTSIDE_WINDOW, STALE;

        /** Redis 값에는 소문자로 나간다 — 192 가 그대로 쓰는 계약 문자열이다. */
        public String wire() {
            return name().toLowerCase(java.util.Locale.ROOT);
        }
    }

    public static State evaluate(OffsetDateTime now, OperatingWindow window, OffsetDateTime lastPollRunAt,
                                 Duration staleAfter) {
        if (!window.contains(now.toLocalTime())) {
            return State.OUTSIDE_WINDOW;
        }
        // 창 안인데 회차가 하나도 없으면 아직 못 받은 것이다. ok 라고 하면 읽는 쪽이 "정보 없음" 으로 오해한다.
        if (lastPollRunAt == null) {
            return State.STALE;
        }
        return Duration.between(lastPollRunAt, now).compareTo(staleAfter) > 0 ? State.STALE : State.OK;
    }

    /** Redis 에 쓰는 값. 회차가 없으면 {@code last_poll_run_at} 은 null 로 둔다 — 0 이나 빈 문자열로 속이지 않는다. */
    public static Map<String, Object> value(State state, OffsetDateTime lastPollRunAt, OperatingWindow window,
                                            OffsetDateTime updatedAt) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("state", state.wire());
        out.put("last_poll_run_at", Times.format(lastPollRunAt));
        out.put("window", window.toString());
        out.put("updated_at", Times.format(updatedAt));
        return out;
    }
}
