package com.ssafy.s15p21a104.load.bikepred;

import java.math.BigDecimal;

/**
 * bike_stock_pred 한 행. 대여소 × 요일 × 30분 슬롯마다 한 행이고, 날짜 축이 없는 정적 표다.
 *
 * @param rentalId         대여소 ID ({@code ST-xxx}). {@code bike_station.rental_id} 와 같은 체계지만
 *                         <b>마스터에 없는 대여소가 섞일 수 있다</b> — 예측 표가 더 최근이라 신설 대여소를 담는다
 * @param dowType          0 평일 / 1 토 / 2 일·공휴일
 * @param timeSlot         30분 단위 슬롯 (0~47)
 * @param expBikes         예상 잔여 대수. {@code NUMERIC(5,1)} 이라 소수 1자리로 줄여 담는다
 * @param pEmpty           0대 확률. {@code NUMERIC(4,3)} 이라 소수 3자리
 * @param pFull            만차 확률. {@code NUMERIC(4,3)}
 * @param source           어떤 예측기인가 — {@code avg} | {@code model}. 원천 CSV 의 열을 그대로 읽는다(하드코딩하지 않는다).
 *                         lightgbm 예측기도 행 값은 {@code model} 이라 예측기 이름과 다르다
 * @param predictionSource 그 칸이 실제 관측인가 대체값인가 — {@code observed_avg} |
 *                         {@code station_time_fallback}(같은 대여소·같은 시간대의 다른 요일 평균) |
 *                         {@code station_global_fallback}(같은 대여소 전체 평균). 다른 대여소 값은 끌어오지 않는다.
 *                         축이 {@code source} 와 다르므로 한 열에 섞지 않는다. 값이 없으면 null
 */
public record BikeStockPredRow(String rentalId, int dowType, int timeSlot,
                               BigDecimal expBikes, BigDecimal pEmpty, BigDecimal pFull,
                               String source, String predictionSource) {
}
