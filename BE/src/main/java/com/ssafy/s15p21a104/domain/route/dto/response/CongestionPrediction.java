package com.ssafy.s15p21a104.domain.route.dto.response;

/**
 * 경로 후보의 혼잡 예측 (S15P21A104-236, FE-BE 통합 계약 §2·상세참고 §2.4).
 *
 * <p>{@code dataStatus=AVAILABLE}일 때만 수치·등급·근거·최악 구간이 있다. 나머지는 네 필드가
 * 전부 null이다 — 결측을 0%나 LOW로 바꾸지 않는다.
 *
 * <p>2026-09-22 기준 변경: {@code congestionPercent}는 시간 가중 평균이 아니라 "가장 혼잡한
 * 구간"의 최대값이다(랭킹·표시 통일).
 */
public record CongestionPrediction(
        /** 예상 혼잡도(%). 0·100 초과 유효, null은 예측값 없음. */
        Double congestionPercent,
        /** 서버 판정 등급. FE가 계산하지 않는다. */
        CongestionGrade congestionGrade,
        /** 데이터 제공 상태. null 불가. */
        CongestionDataStatus dataStatus,
        /** 예측 근거. 예측값이 없으면 null. */
        PredictionBasis predictionBasis,
        /** 가장 혼잡한 구간 위치·값. 예측값이 없으면 null(2026-09-22). */
        WorstSegmentResponse worstSegment
) {
}
