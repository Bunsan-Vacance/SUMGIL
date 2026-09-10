package com.ssafy.s15p21a104.domain.route.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** KTDB 철도교차점(node). {@code station}과는 별도 ID 체계다 — BE/scripts/railgeometry/README.md 참고. */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "rail_node")
public class RailNode {

    @Id
    @Column(name = "node_id", length = 24)
    private String nodeId;

    @Column(name = "lat", nullable = false)
    private Double lat;

    @Column(name = "lng", nullable = false)
    private Double lng;

    @Column(name = "station_name_raw", length = 100)
    private String stationNameRaw;

    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    /** 테스트 전용 — 실제 JPA/DB 없이 노드 매칭 로직을 검증하기 위함. */
    public RailNode(String nodeId, double lat, double lng, String stationNameRaw) {
        this.nodeId = nodeId;
        this.lat = lat;
        this.lng = lng;
        this.stationNameRaw = stationNameRaw;
    }
}
