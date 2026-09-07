package com.ssafy.s15p21a104.domain.route.entity;

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
public class EdgeTimeId implements Serializable {

    @Column(name = "from_node", length = 24)
    private String fromNode;

    @Column(name = "to_node", length = 24)
    private String toNode;

    @Enumerated(EnumType.STRING)
    @Column(name = "mode", length = 8)
    private TravelMode mode;

    @Column(name = "dow_type")
    private Integer dowType;

    @Column(name = "time_slot")
    private Integer timeSlot;
}
