package com.ssafy.s15p21a104.domain.bike.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import java.io.Serializable;
import java.time.LocalDate;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** {@code bike_stock_pred_daily} 복합키 (S15P21A104-309, V10). {@link BikeStockPredId} 의 요일 자리에 날짜가 온다. */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor
@EqualsAndHashCode
@Embeddable
public class BikeStockPredDailyId implements Serializable {

    @Column(name = "rental_id", length = 24)
    private String rentalId;

    /** 대상 날짜 (KST). */
    @Column(name = "pred_date")
    private LocalDate predDate;

    @Column(name = "time_slot")
    private Integer timeSlot;
}
