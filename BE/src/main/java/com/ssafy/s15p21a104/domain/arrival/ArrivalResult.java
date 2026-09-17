package com.ssafy.s15p21a104.domain.arrival;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 실시간 도착 조회 결과(S15P21A104-192).
 *
 * @param status 상태 구분
 * @param trains 도착 후보 목록. LIVE일 때만 비어 있지 않다
 * @param updatedAt 역별 키 갱신 시각. 키 없으면 null
 */
public record ArrivalResult(
        ArrivalStatus status,
        List<ArrivalTrain> trains,
        OffsetDateTime updatedAt
) {
    /**
     * 도착 후보 1건. FE 문서 §5.1 계약 필드 그대로.
     *
     * @param trainId 열차 ID
     * @param direction 방면
     * @param arrivalTime 도착 예정 시각
     * @param updatedAt 갱신 시각
     * @param source LIVE 고정 (MOCK은 FE가 자체 처리)
     */
    public record ArrivalTrain(
            String trainId,
            String direction,
            OffsetDateTime arrivalTime,
            OffsetDateTime updatedAt,
            String source
    ) {
    }
}
