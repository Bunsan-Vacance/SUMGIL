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

/**
 * 따릉이 재고 예측 — 날짜축(모델) 표 (S15P21A104-309, V10). 조회는 이 표를 먼저 보고, 행이 없으면
 * {@link BikeStockPred}(요일축 평균)로 떨어진다. 비어 있어도 되는 표다.
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "bike_stock_pred_daily")
public class BikeStockPredDaily {

    @EmbeddedId
    private BikeStockPredDailyId id;

    @Column(name = "exp_bikes", precision = 5, scale = 1, nullable = false)
    private BigDecimal expBikes;

    @Column(name = "p_empty", precision = 4, scale = 3, nullable = false)
    private BigDecimal pEmpty;

    @Column(name = "p_full", precision = 4, scale = 3, nullable = false)
    private BigDecimal pFull;

    @Column(name = "source", length = 16, nullable = false)
    private String source;

    /** 관측/대체 등급. lightgbm 산출물에는 없어 지금은 null 이다. */
    @Column(name = "prediction_source", length = 32)
    private String predictionSource;

    /** 예측 산출 시각(사이드카). 응답 {@code predictedAt} 으로 나간다 — 적재 시각과 다르다. */
    @Column(name = "generated_at", nullable = false)
    private OffsetDateTime generatedAt;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
