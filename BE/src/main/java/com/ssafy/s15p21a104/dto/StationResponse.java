package com.ssafy.s15p21a104.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/** GET /api/stations/nearby 응답의 개별 대여소 항목 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class StationResponse {
    private String name;
    private Double lat;
    private Double lng;
    private Integer rackTotal;
    private Double distanceMeters;
}
