package com.ssafy.s15p21a104.domain.bike.entity;

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
@Table(name = "bike_stock_pred")
public class BikeStockPred {

    @EmbeddedId
    private BikeStockPredId id;

    @Column(name = "exp_bikes", precision = 5, scale = 1, nullable = false)
    private BigDecimal expBikes;

    @Column(name = "p_empty", precision = 4, scale = 3, nullable = false)
    private BigDecimal pEmpty;

    @Column(name = "p_full", precision = 4, scale = 3, nullable = false)
    private BigDecimal pFull;

    @Column(name = "source", length = 8, nullable = false)
    private String source;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
