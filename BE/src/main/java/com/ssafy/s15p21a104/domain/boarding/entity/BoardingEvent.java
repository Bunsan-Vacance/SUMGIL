package com.ssafy.s15p21a104.domain.boarding.entity;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 탑승 확인 이벤트(S15P21A104-313, BE/docs/api/boarding-check-api-design.md).
 *
 * <p>로그인이 없는 공개 API라 사용자를 식별하지 않는다 — "어떤 구간에 탑승 이벤트가 있었다"만 기록해
 * AI·다른 BE 도메인이 직접 테이블을 읽어 쓰게 한다(congestion_pred·bike_stock_pred와 같은 소비 패턴).
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "boarding_event")
public class BoardingEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Enumerated(EnumType.STRING)
    @Column(name = "mode", nullable = false, length = 16)
    private TravelMode mode;

    @Column(name = "from_node_id", nullable = false, length = 24)
    private String fromNodeId;

    @Column(name = "from_node_name", length = 64)
    private String fromNodeName;

    @Column(name = "to_node_id", nullable = false, length = 24)
    private String toNodeId;

    @Column(name = "to_node_name", length = 64)
    private String toNodeName;

    @Column(name = "route_id", length = 32)
    private String routeId;

    @Column(name = "route_name", length = 64)
    private String routeName;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 16)
    private BoardingStatus status;

    @Column(name = "departure_time", length = 8)
    private String departureTime;

    @Column(name = "reported_at", nullable = false)
    private OffsetDateTime reportedAt;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt;

    private BoardingEvent(TravelMode mode, String fromNodeId, String fromNodeName,
                           String toNodeId, String toNodeName, String routeId, String routeName,
                           BoardingStatus status, String departureTime, OffsetDateTime reportedAt) {
        this.mode = mode;
        this.fromNodeId = fromNodeId;
        this.fromNodeName = fromNodeName;
        this.toNodeId = toNodeId;
        this.toNodeName = toNodeName;
        this.routeId = routeId;
        this.routeName = routeName;
        this.status = status;
        this.departureTime = departureTime;
        this.reportedAt = reportedAt;
        this.createdAt = OffsetDateTime.now();
    }

    public static BoardingEvent of(TravelMode mode, String fromNodeId, String fromNodeName,
                                    String toNodeId, String toNodeName, String routeId, String routeName,
                                    BoardingStatus status, String departureTime, OffsetDateTime reportedAt) {
        return new BoardingEvent(mode, fromNodeId, fromNodeName, toNodeId, toNodeName,
                routeId, routeName, status, departureTime, reportedAt);
    }
}
