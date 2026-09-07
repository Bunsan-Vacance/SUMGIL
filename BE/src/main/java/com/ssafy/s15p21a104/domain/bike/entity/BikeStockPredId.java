package com.ssafy.s15p21a104.domain.bike.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import java.io.Serializable;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor
@EqualsAndHashCode
@Embeddable
public class BikeStockPredId implements Serializable {

    @Column(name = "rental_id", length = 24)
    private String rentalId;

    @Column(name = "dow_type")
    private Integer dowType;

    @Column(name = "time_slot")
    private Integer timeSlot;
}
