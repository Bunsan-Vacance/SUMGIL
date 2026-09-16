package com.ssafy.s15p21a104.domain.congestion.entity;

import jakarta.persistence.Column;
import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "congestion")
public class Congestion {

    @EmbeddedId
    private CongestionId id;

    @Column(name = "level", precision = 4, scale = 1, nullable = false)
    private BigDecimal level;

    @Column(name = "source", length = 16, nullable = false)
    private String source;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
