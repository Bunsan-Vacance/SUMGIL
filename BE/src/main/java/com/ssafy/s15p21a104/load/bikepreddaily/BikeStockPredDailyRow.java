package com.ssafy.s15p21a104.load.bikepreddaily;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * bike_stock_pred_daily 한 행 (S15P21A104-309). 대여소 × <b>날짜</b> × 30분 슬롯마다 한 행이다.
 * 열 의미는 {@link com.ssafy.s15p21a104.load.bikepred.BikeStockPredRow} 와 같고, 요일 대신 날짜가 키다.
 *
 * @param predDate         대상 날짜 (KST). AI 사이드카의 {@code target_date} 와 같다
 * @param predictionSource 관측/대체 등급. lightgbm 산출물에는 이 열이 없어 null 이다
 * @param generatedAt      그 행이 나온 산출물의 사이드카 {@code generated_at}. 파일마다 다를 수 있어 행에 싣는다
 */
public record BikeStockPredDailyRow(String rentalId, LocalDate predDate, int timeSlot,
                                    BigDecimal expBikes, BigDecimal pEmpty, BigDecimal pFull,
                                    String source, String predictionSource, OffsetDateTime generatedAt) {
}
