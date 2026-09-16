package com.ssafy.s15p21a104.domain.congestion.dto.response;

import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 혼잡도 조회 응답(S15P21A104-150). {@code congestion} 테이블 값을 그대로 옮긴다 — 값을 가공·추정하지 않는다.
 */
public record CongestionResponse(
        CongestionTarget targetType,
        String targetId,
        int dowType,
        int timeSlot,
        BigDecimal level,
        String source,
        OffsetDateTime updatedAt
) {
}
