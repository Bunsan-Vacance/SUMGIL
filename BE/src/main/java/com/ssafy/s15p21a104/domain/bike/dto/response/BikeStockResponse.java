package com.ssafy.s15p21a104.domain.bike.dto.response;

import com.ssafy.s15p21a104.domain.bike.stock.BikeStockStatus;
import java.time.OffsetDateTime;

public record BikeStockResponse(
        String rentalId,
        Integer availableBikes,
        Integer rackCount,
        OffsetDateTime stockUpdatedAt,
        BikeStockStatus status
) {
}
