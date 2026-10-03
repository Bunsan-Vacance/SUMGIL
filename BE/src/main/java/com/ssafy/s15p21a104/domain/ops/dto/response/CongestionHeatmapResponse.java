package com.ssafy.s15p21a104.domain.ops.dto.response;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 혼잡도 예측 호선×슬롯 히트맵. 원천은 {@code congestion_pred}이며 정적 {@code congestion} 표와 다르다.
 * 해당 날짜 데이터가 없으면 200에 {@code lines: []}, generatedAt은 null, predictorVersions는 빈 목록이다.
 */
public record CongestionHeatmapResponse(
        LocalDate date,
        String source,
        OffsetDateTime generatedAt,
        List<String> predictorVersions,
        int slotFrom,
        int slotTo,
        List<HeatmapLine> lines
) {
}
