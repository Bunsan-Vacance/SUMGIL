package com.ssafy.s15p21a104.domain.bike.stock;

import java.time.OffsetDateTime;

/** {@link BikeStockReader} 조회 결과. UNAVAILABLE이면 available·updatedAt은 null이다. */
public record BikeStock(Integer available, OffsetDateTime updatedAt, BikeStockStatus status) {

    static BikeStock unavailable() {
        return new BikeStock(null, null, BikeStockStatus.UNAVAILABLE);
    }
}
