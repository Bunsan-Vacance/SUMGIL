package com.ssafy.s15p21a104.domain.route.loader;

import java.util.Objects;

/**
 * 그래프 조립용 SUBWAY 구간 행 원시 데이터.
 *
 * <p>{@code edge_time} 테이블의 SUBWAY 행 1개를 대표 슬롯 1개로 필터한 뒤 1건이다.
 * 실제 DB 조회 계약(Repository)이 이 값을 만들고 조립 로더는 이를 유향 엣지 1개로 바꾼다.
 */
public record RouteEdgeRow(
        String fromNode,
        String toNode,
        String routeId,
        int travelSec,
        int waitSec
) {
    /**
     * 원시 행 값을 검증한다.
     */
    public RouteEdgeRow {
        Objects.requireNonNull(fromNode, "fromNode");
        Objects.requireNonNull(toNode, "toNode");
        Objects.requireNonNull(routeId, "routeId");
        if (travelSec < 0) {
            throw new IllegalArgumentException("travelSec는 0 이상이어야 한다.");
        }
        if (waitSec < 0) {
            throw new IllegalArgumentException("waitSec는 0 이상이어야 한다.");
        }
    }
}
