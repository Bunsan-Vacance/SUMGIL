package com.ssafy.s15p21a104.domain.arrival.dto.response;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 실시간 도착 조회 응답(S15P21A104-192, FE 문서 §5.1 계약).
 *
 * @param status LIVE · NO_INFO · OUTSIDE_WINDOW · STALE
 * @param trains 도착 후보. LIVE일 때만 비어 있지 않다
 * @param updatedAt 역별 키 갱신 시각. 키 없으면 null
 */
public record ArrivalResponse(
        String status,
        List<ArrivalTrainResponse> trains,
        OffsetDateTime updatedAt
) {
    /**
     * @param trainId 열차 ID
     * @param direction 방면
     * @param arrivalTime 도착 예정 시각 (offset ISO)
     * @param updatedAt 갱신 시각 (offset ISO)
     * @param source LIVE 고정
     */
    public record ArrivalTrainResponse(
            String trainId,
            String direction,
            OffsetDateTime arrivalTime,
            OffsetDateTime updatedAt,
            String source
    ) {
    }
}
