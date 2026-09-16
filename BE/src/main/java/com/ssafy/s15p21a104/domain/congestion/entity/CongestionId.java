package com.ssafy.s15p21a104.domain.congestion.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
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
public class CongestionId implements Serializable {

    @Enumerated(EnumType.STRING)
    @Column(name = "target_type", length = 8)
    private CongestionTarget targetType;

    @Column(name = "target_id", length = 24)
    private String targetId;

    @Column(name = "dow_type")
    private Integer dowType;

    @Column(name = "time_slot")
    private Integer timeSlot;
}
