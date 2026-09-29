package com.ssafy.s15p21a104.domain.route.dto.request;

import java.time.Clock;
import java.time.LocalDateTime;
import java.time.ZoneId;

/**
 * 요청의 출발 시각을 확정한다 — 생략됐으면 "지금" 을 채운다 (S15P21A104-306).
 *
 * <p>요청으로 들어오는 {@code departureTime} 은 시간대가 없는 <b>서울 벽시계</b>다(FE 계약).
 * 생략됐을 때 채우는 "지금" 도 같은 기준이어야 한다. 그냥 {@code LocalDateTime.now()} 를 쓰면
 * <b>서버 JVM 시간대</b>를 따라가는데, prod 컨테이너가 UTC 라 서울보다 9시간 이른 값이 된다.
 * 그 값이 {@code DepartureSlot}(요일·30분 슬롯)과 실시간 혼잡도 창 판정에 그대로 쓰여
 * 조용히 틀린 결과를 낸다 — 새벽 0~9시(KST)에는 <b>요일 유형까지</b> 어긋난다.
 *
 * <p>배포 이미지에도 {@code -Duser.timezone=Asia/Seoul} 을 넣지만, 그 설정이 빠지거나 바뀌어도
 * 요청 해석만은 안 깨지게 여기서 못 박는다.
 */
public final class RequestedDeparture {

    /** 요청 시각이 기준으로 삼는 시간대. 서버 시간대와 무관하게 이 값을 쓴다. */
    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");

    private RequestedDeparture() {
    }

    /**
     * @param requested 요청이 준 출발 시각(서울 벽시계). null 이면 지금 출발이다
     * @param clock     현재 시각. 어느 시간대의 시계든 서울 기준으로 환산한다
     * @return 확정된 출발 시각. 항상 서울 벽시계다
     */
    public static LocalDateTime resolve(LocalDateTime requested, Clock clock) {
        return requested != null ? requested : LocalDateTime.now(clock.withZone(SEOUL));
    }
}
