package com.ssafy.s15p21a104.domain.ops.dto.response;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionStatus;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockStatus;
import java.time.OffsetDateTime;

/**
 * 대여소 1곳의 실시간 재고 + 도착 시각 예측. 값을 알 수 없으면 null이며 0으로 해석하면 안 된다.
 * 예측이 UNAVAILABLE이면 predictedBikes·availabilityProbability·predictedAt은 null이다.
 */
public record BikeStockOverviewItem(
        String rentalId,
        String name,
        double lat,
        double lng,
        Integer rackCount,
        Integer availableBikes,
        BikeStockStatus stockStatus,
        OffsetDateTime stockUpdatedAt,
        Integer predictedBikes,
        Double availabilityProbability,
        BikePredictionStatus predictionStatus,
        OpsPredictionSource predictionSource,
        OffsetDateTime predictedAt
) {
}
