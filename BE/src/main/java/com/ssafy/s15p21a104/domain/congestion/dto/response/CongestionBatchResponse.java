package com.ssafy.s15p21a104.domain.congestion.dto.response;

import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 혼잡도 일괄 조회 응답(S15P21A104-354). 여러 대상·여러 시각을 한 번에 조회한 결과로,
 * 값은 {@code congestion} 테이블에서 그대로 옮기며 가공하지 않는다.
 *
 * <p>{@code departureTimes}는 정규화(기본값·중복 제거) 뒤의 시각 목록이다.
 */
public record CongestionBatchResponse(
        CongestionTarget targetType,
        List<LocalDateTime> departureTimes,
        List<CongestionBatchTarget> targets
) {
}
