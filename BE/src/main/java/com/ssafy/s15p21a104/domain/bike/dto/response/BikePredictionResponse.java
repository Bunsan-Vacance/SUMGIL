package com.ssafy.s15p21a104.domain.bike.dto.response;

import java.time.OffsetDateTime;

/**
 * 따릉이 도착 시 예측 응답 (S15P21A104-237, FE-BE 통합 계약 §6.1).
 *
 * <p>{@code UNAVAILABLE}이면 예측값·근거·산출 시각이 전부 null이다 — 예측 불가를
 * 재고 0으로 바꾸지 않는다. {@code arrivalTime}은 요청 시각과 같은 instant를
 * 그대로 돌려준다.
 */
public record BikePredictionResponse(
        BikePredictionStatus status,
        Integer predictedBikes,
        Double availabilityProbability,
        OffsetDateTime predictedAt,
        OffsetDateTime arrivalTime,
        String rentalId,
        BikePredictionSource source
) {
}
