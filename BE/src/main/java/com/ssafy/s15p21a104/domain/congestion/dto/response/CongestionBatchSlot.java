package com.ssafy.s15p21a104.domain.congestion.dto.response;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;

/**
 * 혼잡도 일괄 조회의 시각별 한 칸(S15P21A104-354). 요청 시각과 변환된 슬롯 키를 함께 싣는다.
 * 데이터가 없는 조합은 {@code level}·{@code source}·{@code updatedAt}이 모두 {@code null}이다
 * (값을 추정·보간하지 않는다).
 */
public record CongestionBatchSlot(
        LocalDateTime departureTime,
        int dowType,
        int timeSlot,
        BigDecimal level,
        String source,
        OffsetDateTime updatedAt
) {
}
