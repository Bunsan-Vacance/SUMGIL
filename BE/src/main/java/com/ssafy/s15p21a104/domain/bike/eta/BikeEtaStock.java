package com.ssafy.s15p21a104.domain.bike.eta;

import java.time.OffsetDateTime;

/**
 * AI 실시간 모델이 준 도착 시점 재고 (S15P21A104-309). 도착 예측 응답에 그대로 옮길 모양으로 바꿔 둔 값이다.
 *
 * @param predictedBikes          AI {@code predicted_stock} 을 반올림한 대수
 * @param availabilityProbability {@code 1 - p_empty} (0~1)
 * @param predictedAt             AI 를 부른 시각. 실시간 예측이라 이 순간이 산출 시각이다
 */
public record BikeEtaStock(int predictedBikes, double availabilityProbability, OffsetDateTime predictedAt) {
}
