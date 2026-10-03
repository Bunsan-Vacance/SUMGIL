package com.ssafy.s15p21a104.domain.ops.dto.response;

/**
 * 운영자 뷰 일괄 예측의 출처. 일괄 조회는 AI 모델을 부르지 않고 {@code bike_stock_pred} 표만 읽으므로 항상 TABLE이다.
 * 단건 {@code /api/bike-stations/{id}/prediction}의 MODEL/MOCK과 다른 축임을 응답에서 드러내기 위한 값이다.
 */
public enum OpsPredictionSource {
    TABLE
}
