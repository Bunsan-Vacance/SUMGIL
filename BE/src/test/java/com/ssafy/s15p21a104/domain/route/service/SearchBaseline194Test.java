package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-194 탐색 성능 기준선.
 * DB·Redis·외부 API 없이 인메모리 그래프 탐색 지연을 측정한다.
 * 서버 기동 없이 단위 레벨에서 동일조건 반복 측정한다.
 */
class SearchBaseline194Test {

    /** 기준선 측정용 그래프: 100개 정점 체인 + 지름길 10개. */
    private static RouteGraph baselineGraph() {
        List<com.ssafy.s15p21a104.domain.route.graph.Edge> edges = new ArrayList<>();
        for (int i = 0; i < 100; i++) {
            edges.add(subway("S" + i, "S" + (i + 1), "L1", 100));
        }
        for (int i = 0; i < 10; i++) {
            edges.add(subway("S" + (i * 10), "S" + (i * 10 + 5), "L2", 200));
        }
        return graphOf(edges.toArray(new com.ssafy.s15p21a104.domain.route.graph.Edge[0]));
    }

    @Test
    @DisplayName("194-B1: 100정점 그래프 탐색 p95가 500ms 미만이다 (단위 기준선)")
    void b1_탐색지연_기준선() {
        var service = RouteTestFixtures.serviceWith(baselineGraph(), Set.of());
        // 웜업 5회.
        for (int i = 0; i < 5; i++) {
            service.search("S0", "S100", null, null, null);
        }
        // 측정 20회.
        List<Long> elapsedMs = new ArrayList<>();
        for (int i = 0; i < 20; i++) {
            long start = System.nanoTime();
            List<RouteSearchResponse> result = service.search("S0", "S100", null, null, null);
            long elapsed = (System.nanoTime() - start) / 1_000_000;
            elapsedMs.add(elapsed);
            assertTrue(result.size() >= 1);
        }
        elapsedMs.sort(Long::compareTo);
        long p95 = elapsedMs.get((int) Math.ceil(0.95 * elapsedMs.size()) - 1);
        long max = elapsedMs.get(elapsedMs.size() - 1);
        long p50 = elapsedMs.get(10);
        try {
            java.nio.file.Files.writeString(
                    java.nio.file.Path.of("build/baseline-194.txt"),
                    "BASELINE search p50=" + p50 + "ms p95=" + p95 + "ms max=" + max + "ms (n=20, 100nodes)");
        } catch (java.io.IOException e) {
            // 측정 기록 실패는 무시 (테스트 판정과 무관).
        }
        assertTrue(p95 < 500, "p95=" + p95 + "ms, 기준선 500ms 초과");
    }

    @Test
    @DisplayName("194-B2: 외부 호출 없이 탐색이 끝나고 geometry는 unavailable이다")
    void b2_외부호출없음() {
        var service = RouteTestFixtures.serviceWith(baselineGraph(), Set.of());

        List<RouteSearchResponse> result = service.search("S0", "S100", null, null, null);

        assertTrue(result.size() >= 1);
        // noop 레지스트리라 geometry 없이 응답 — 외부 호출 0건.
        assertTrue(result.get(0).legs().stream()
                .allMatch(leg -> leg.geometryStatus().equals("unavailable")));
    }
}
