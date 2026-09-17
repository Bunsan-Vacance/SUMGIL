package com.ssafy.s15p21a104.domain.bus.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "bus_route")
public class BusRoute {

    @Id
    @Column(name = "route_id", length = 24)
    private String routeId;

    @Column(name = "name", length = 50, nullable = false)
    private String name;

    /**
     * 배차간격(분). 노선당 대표값 하나이며 시간대별로 갈리지 않는다 (V6).
     * NULL 은 원천이 값을 주지 않은 노선 — 도착정보 API 가 다루지 않는 마을버스가 대부분이다.
     */
    @Column(name = "headway_min")
    private Integer headwayMin;

    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;
}
