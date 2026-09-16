package com.ssafy.s15p21a104.consume;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 회차 지연 분포 (S15P21A104-171 · 174 perf 규약).
 *
 * <p>규약이 "평균이 아니라 median·p95" 를 요구한다(perf/README.md 원칙 3). 순위 기반(nearest-rank)으로 계산해
 * 기존 기록(2026-09-08·09-11 edge_time, n=5 라 p95 = 최댓값)과 같은 정의를 쓴다.
 */
class LatencyStatsTest {

    @Test
    void 비어_있으면_전부_0() {
        LatencyStats stats = LatencyStats.of(List.of());

        assertEquals(0, stats.count());
        assertEquals(0, stats.min());
        assertEquals(0, stats.median());
        assertEquals(0, stats.p95());
        assertEquals(0, stats.max());
    }

    @Test
    void 한_건이면_전부_같은_값() {
        LatencyStats stats = LatencyStats.of(List.of(42L));

        assertEquals(1, stats.count());
        assertEquals(42, stats.min());
        assertEquals(42, stats.median());
        assertEquals(42, stats.p95());
        assertEquals(42, stats.max());
    }

    @Test
    @DisplayName("홀수 개의 median 은 가운데 값")
    void 홀수_median() {
        LatencyStats stats = LatencyStats.of(List.of(5L, 1L, 3L, 2L, 4L));

        assertEquals(5, stats.count());
        assertEquals(1, stats.min());
        assertEquals(3, stats.median());
        assertEquals(5, stats.max());
    }

    @Test
    @DisplayName("n=5 면 p95 는 최댓값과 같다 — 기존 기록(2026-09-08)과 같은 정의")
    void n5_p95_는_최댓값() {
        LatencyStats stats = LatencyStats.of(List.of(10L, 20L, 30L, 40L, 50L));

        assertEquals(50, stats.p95());
        assertEquals(stats.max(), stats.p95());
    }

    @Test
    @DisplayName("n=100 이면 p95 는 95번째로 작은 값")
    void n100_p95() {
        List<Long> values = new ArrayList<>();
        for (long i = 1; i <= 100; i++) {
            values.add(i);
        }

        LatencyStats stats = LatencyStats.of(values);

        assertEquals(100, stats.count());
        assertEquals(1, stats.min());
        assertEquals(50, stats.median());
        assertEquals(95, stats.p95());
        assertEquals(100, stats.max());
    }

    @Test
    @DisplayName("입력 순서를 바꿔도 결과가 같다 — 원본 리스트를 망가뜨리지 않는다")
    void 입력을_건드리지_않는다() {
        List<Long> values = new ArrayList<>(List.of(30L, 10L, 20L));

        LatencyStats stats = LatencyStats.of(values);

        assertEquals(20, stats.median());
        assertEquals(List.of(30L, 10L, 20L), values, "호출자의 리스트가 정렬돼 버리면 안 된다");
    }

    @Test
    @DisplayName("음수는 버린다 — 시각이 어긋나면(파드 시계 차이) 지연이 음수로 나온다")
    void 음수는_버린다() {
        LatencyStats stats = LatencyStats.of(List.of(-5L, 10L, 20L));

        assertEquals(2, stats.count(), "음수 1건은 세지 않는다");
        assertEquals(10, stats.min());
    }
}
