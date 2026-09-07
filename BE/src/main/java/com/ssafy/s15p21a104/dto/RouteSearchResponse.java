package com.ssafy.s15p21a104.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * GET /api/routes/search 응답 형태.
 * 알고리즘 파트 로직이 아직 안 붙어있어서 컨트롤러에서 mock 데이터로 채워서 내려준다.
 * 이 구조 자체가 팀 인터페이스 계약 초안 (팀 논의로 필드 추가/변경 가능).
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RouteSearchResponse {

    private String origin;
    private String destination;
    private Double baselineTotalMin;
    private List<ModeSummaryItem> modeSummary;
    private List<AdjustmentItem> adjustments;
    private List<ReversalItem> reversals;
    private List<CheckedOtherItem> checkedOthers;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ModeSummaryItem {
        private String emoji;
        private String label;
        private Double min;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AdjustmentItem {
        private String label;
        private Double min;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ReversalItem {
        private String station;
        private Double baselineMin;
        private Double bikeMin;
        private Double savedMin;
        private String option;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CheckedOtherItem {
        private String station;
        private String note;
        private Double bikeMin;
    }
}
