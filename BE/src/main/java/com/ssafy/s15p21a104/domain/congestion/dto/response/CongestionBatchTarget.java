package com.ssafy.s15p21a104.domain.congestion.dto.response;

import java.util.List;

/**
 * 혼잡도 일괄 조회의 대상 하나(S15P21A104-354). {@code slots}는 정규화된 요청 시각 순서이며
 * 모든 시각을 빠짐없이 포함한다.
 */
public record CongestionBatchTarget(
        String targetId,
        List<CongestionBatchSlot> slots
) {
}
