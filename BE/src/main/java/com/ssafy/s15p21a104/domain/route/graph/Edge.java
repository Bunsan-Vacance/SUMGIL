package com.ssafy.s15p21a104.domain.route.graph;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.Objects;

/**
 * 그래프의 유향 엣지 1개.
 *
 * <p>{@code edge_time} 테이블의 SUBWAY 행 1개에 대응한다.
 * 같은 출발·도착 구간에 양방향 행이 있으면 엣지가 2개가 되고,
 * 단방향 행만 있으면 엣지가 1개뿐이다(역방향 임의 생성 금지).
 *
 * <p>엣지가 여러 노선에 걸치더라도 {@code routeId}는 구간(엣지)의 소속 노선을 나타낸다.
 * 정점(역 자체)이 특정 노선 하나에 묶이지 않는다.
 *
 * <p>수단 구분({@code mode})은 탐색 비용에 쓰지 않고 그대로 전달만 한다.
 * SUBWAY 행은 로더가 {@code SUBWAY}로 고정 주입한다.
 *
 * <p>불변(immutable) 값 객체이다.
 */
public record Edge(
        String fromNode,
        String toNode,
        String routeId,
        int travelSec,
        int waitSec,
        TravelMode mode
) {
    /**
     * 엣지 값을 검증한다.
     */
    public Edge {
        Objects.requireNonNull(fromNode, "fromNode");
        Objects.requireNonNull(toNode, "toNode");
        Objects.requireNonNull(routeId, "routeId");
        Objects.requireNonNull(mode, "mode");
        if (travelSec < 0) {
            throw new IllegalArgumentException("travelSec는 0 이상이어야 한다.");
        }
        if (waitSec < 0) {
            throw new IllegalArgumentException("waitSec는 0 이상이어야 한다.");
        }
    }
}
