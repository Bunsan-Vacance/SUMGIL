package com.ssafy.s15p21a104.domain.route.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/**
 * KTDB 철도중심선(link) — 역 사이 실제 선로 좌표.
 * {@code line_id}는 KTDB {@code RAILLINEN3}(지하철 서비스명)를 우리 {@code line}과 매칭한 결과이며,
 * 매칭 실패 시 null이다(우리 노선표 밖 — 정상). BE/scripts/railgeometry/README.md 참고.
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "rail_link_geometry")
public class RailLinkGeometry {

    @Id
    @Column(name = "link_id", length = 24)
    private String linkId;

    @Column(name = "from_node_id", length = 24, nullable = false)
    private String fromNodeId;

    @Column(name = "to_node_id", length = 24, nullable = false)
    private String toNodeId;

    @Column(name = "line_name_raw", length = 100, nullable = false)
    private String lineNameRaw;

    @Column(name = "physical_line_name_raw", length = 100)
    private String physicalLineNameRaw;

    @Column(name = "line_id", length = 16)
    private String lineId;

    @Column(name = "length_km", precision = 10, scale = 3)
    private BigDecimal lengthKm;

    /** GeoJSON LineString 문자열: {"type":"LineString","coordinates":[[lng,lat],...]}. */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "geometry", nullable = false)
    private String geometry;

    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    /** 테스트 전용 — BFS 경로 탐색 로직을 실제 JPA/DB 없이 검증하기 위함. */
    public RailLinkGeometry(String linkId, String fromNodeId, String toNodeId, String lineId, String geometry) {
        this.linkId = linkId;
        this.fromNodeId = fromNodeId;
        this.toNodeId = toNodeId;
        this.lineId = lineId;
        this.geometry = geometry;
    }
}
