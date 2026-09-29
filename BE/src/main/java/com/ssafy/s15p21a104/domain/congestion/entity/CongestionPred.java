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

/**
 * 구간(링크) 혼잡도 예측(S15P21A104-158, 통지 04 1.2절 DDL). AI CROWD 배치 산출물을
 * BE load job이 적재한다(별도 티켓, 이원빈) — 이 엔티티는 읽기 전용으로만 쓴다.
 *
 * <p>{@link Congestion}(노선 단위·정적 통계)과는 별개 테이블이다 — 날짜·방향·링크
 * 축이 있고 {@code level}이 결측(NULL)을 허용한다는 점이 근본적으로 다르다
 * (통지 04 1.1절: 기존 표의 PK로는 표현 불가능).
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "congestion_pred")
public class CongestionPred {

    @EmbeddedId
    private CongestionPredId id;

    /** 보정 혼잡도 %. 결측이면 null — {@link #dataStatus}가 이유를 말한다(값을 지어내지 않음). */
    @Column(name = "level", precision = 5, scale = 1)
    private BigDecimal level;

    @Column(name = "data_status", length = 32, nullable = false)
    private String dataStatus;

    @Column(name = "pred_source", length = 32, nullable = false)
    private String predSource;

    @Column(name = "predictor_version", length = 32, nullable = false)
    private String predictorVersion;

    /** 산출물 meta.generated_at — 재적재·캐시 판정용(통지 04 4절). */
    @Column(name = "generated_at", nullable = false)
    private OffsetDateTime generatedAt;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
