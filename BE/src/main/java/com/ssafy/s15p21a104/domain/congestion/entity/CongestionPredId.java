package com.ssafy.s15p21a104.domain.congestion.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import java.io.Serializable;
import java.time.LocalDate;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * {@code congestion_pred} 복합키(S15P21A104-158, 통지 04 1.2절 DDL).
 *
 * <p>노선 단위·출발 슬롯 1개였던 {@link CongestionId}와 달리, 날짜·링크(구간)·방향·
 * 통과 시각의 슬롯이 축이다. {@code line_id}는 지선·본선이 같은 구간을 공유하는
 * 경우를 막는 방어용 키다(통지 04 1.2절 — 비용 없음).
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor
@EqualsAndHashCode
@Embeddable
public class CongestionPredId implements Serializable {

    @Column(name = "pred_date")
    private LocalDate predDate;

    @Column(name = "from_station_id", length = 24)
    private String fromStationId;

    @Column(name = "to_station_id", length = 24)
    private String toStationId;

    @Column(name = "line_id", length = 16)
    private String lineId;

    @Column(name = "direction", length = 8)
    private String direction;

    @Column(name = "time_slot")
    private Integer timeSlot;
}
