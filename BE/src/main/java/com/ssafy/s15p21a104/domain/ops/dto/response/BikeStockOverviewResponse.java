package com.ssafy.s15p21a104.domain.ops.dto.response;

import java.time.OffsetDateTime;
import java.util.List;

/** 지도 bbox 안 대여소 재고·예측 일괄 응답. {@code truncated}가 true면 limit 때문에 bbox 중심에서 먼 대여소가 잘렸다. */
public record BikeStockOverviewResponse(
        OffsetDateTime arrivalTime,
        int count,
        boolean truncated,
        OffsetDateTime generatedAt,
        List<BikeStockOverviewItem> items
) {
}
