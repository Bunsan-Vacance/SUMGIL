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

    @Column(name = "source", length = 16, nullable = false)
    private String source;

    /**
     * 예측값의 출처 등급 (V5). {@code observed_avg} 는 실제 관측, {@code station_time_fallback}·
     * {@code station_global_fallback} 은 같은 대여소 안의 평균으로 메운 값이다. 이 열이 없던 시절 산출물은 null 이다.
     * {@link #source}(어떤 예측기인가)와 축이 다르므로 섞지 않는다 — 읽는 쪽이 대체값을 관측값과 구분할 수 있어야 한다.
     */
    @Column(name = "prediction_source", length = 32)
    private String predictionSource;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
