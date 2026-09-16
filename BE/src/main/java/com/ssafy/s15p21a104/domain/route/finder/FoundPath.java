package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import java.util.Objects;

/**
 * 최단 경로 탐색 결과 1개(K=1).
 *
 * @param stations 정점 순서(출발역 → 도착역)
 * @param edges 사용 엣지 순서(노선 전환 지점 포함, 각 엣지의 routeId로 구간 노선 확인)
 * @param totalSec 총 소요(초, 환승 상수 포함)
 * @param transferCount 환승 횟수(노선 전환 횟수)
 */
public record FoundPath(
        List<String> stations,
        List<Edge> edges,
        long totalSec,
        int transferCount
) {
    /**
     * 탐색 결과를 검증한다.
     */
    public FoundPath {
        Objects.requireNonNull(stations, "stations");
        Objects.requireNonNull(edges, "edges");
        if (stations.isEmpty()) {
            throw new IllegalArgumentException("stations는 비어 있을 수 없다.");
        }
        if (edges.size() != stations.size() - 1) {
            throw new IllegalArgumentException("edges는 stations보다 1개 적어야 한다.");
        }
        if (totalSec < 0) {
            throw new IllegalArgumentException("totalSec는 0 이상이어야 한다.");
        }
        if (transferCount < 0) {
            throw new IllegalArgumentException("transferCount는 0 이상이어야 한다.");
        }
    }
}
