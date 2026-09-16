package com.ssafy.s15p21a104.domain.bike.entity;

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
@Table(name = "bike_station")
public class BikeStation {

    @Id
    @Column(name = "rental_id", length = 24)
    private String rentalId;

    @Column(name = "name", nullable = false)
    private String name;

    @Column(name = "lat")
    private Double lat;

    @Column(name = "lng")
    private Double lng;

    @Column(name = "dock_count")
    private Integer dockCount;

    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;
}
