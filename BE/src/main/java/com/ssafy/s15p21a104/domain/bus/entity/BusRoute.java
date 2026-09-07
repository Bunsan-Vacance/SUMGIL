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

    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;
}
