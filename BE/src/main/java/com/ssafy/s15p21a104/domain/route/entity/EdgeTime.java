package com.ssafy.s15p21a104.domain.route.entity;

import jakarta.persistence.Column;
import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "edge_time")
public class EdgeTime {

    @EmbeddedId
    private EdgeTimeId id;

    @Column(name = "travel_sec", nullable = false)
    private Integer travelSec;

    @Column(name = "wait_sec", nullable = false)
    private Integer waitSec;

    @Column(name = "source", length = 16, nullable = false)
    private String source;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
