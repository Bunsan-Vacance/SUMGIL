package com.ssafy.s15p21a104.domain.station.dto.response;

/**
 * 역 검색 결과 1행. 환승역은 소속 노선 수만큼 행이 나뉜다(같은 stationId, 다른 lineId/lineName).
 * FE 제안 계약(미승인) — BE/docs/api/api-spec.md 참고.
 */
public record StationSearchResultResponse(
        String stationId,
        String stationName,
        String lineId,
        String lineName,
        Double lat,
        Double lng
) {
}
