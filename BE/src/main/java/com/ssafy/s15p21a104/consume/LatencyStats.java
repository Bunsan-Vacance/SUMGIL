package com.ssafy.s15p21a104.consume;

import java.util.ArrayList;
import java.util.List;

/**
 * 지연 분포 (S15P21A104-171). 회차마다 로그로 남겨 며칠 쌓이면 그대로 perf 기록이 된다.
 *
 * <p>{@code BE/docs/perf/README.md} 원칙 3 이 "평균이 아니라 median·p95" 를 요구한다. 순위 기반(nearest-rank)으로
 * 계산해 기존 기록(2026-09-08·09-11 edge_time)과 같은 정의를 쓴다 — 그 기록들은 n=5 라 p95 가 최댓값과 같다.
 *
 * <p>컨슈머는 이것을 두 구간으로 따로 낸다. 어느 쪽이 늘어나는지 보면 병목이 Kafka 인지 우리 코드인지 갈린다.
 * <pre>
 *   ingested_at ──────→ 레코드 timestamp ──────→ written_at
 *        (produce 구간)          (consume 구간)
 * </pre>
 *
 * @param count  센 건수 (음수 표본은 빠진 뒤의 수)
 * @param min    최솟값(ms)
 * @param median 중앙값(ms)
 * @param p95    95 백분위(ms)
 * @param max    최댓값(ms)
 */
public record LatencyStats(int count, long min, long median, long p95, long max) {

    public static final LatencyStats EMPTY = new LatencyStats(0, 0, 0, 0, 0);

    /**
     * @param millis 지연 표본. 음수는 버린다 — 수집기 파드와 컨슈머 파드의 시계가 어긋나면 음수가 나오는데,
     *               그것을 0 으로 깎으면 분포가 실제보다 좋아 보인다. 호출자의 리스트는 건드리지 않는다
     */
    public static LatencyStats of(List<Long> millis) {
        List<Long> sorted = new ArrayList<>(millis.size());
        for (Long value : millis) {
            if (value != null && value >= 0) {
                sorted.add(value);
            }
        }
        if (sorted.isEmpty()) {
            return EMPTY;
        }
        sorted.sort(null);
        return new LatencyStats(sorted.size(), sorted.get(0), rank(sorted, 0.50), rank(sorted, 0.95),
                sorted.get(sorted.size() - 1));
    }

    /** nearest-rank: 올림한 순위의 값. n=5·p95 면 5번째(=최댓값), n=100·p95 면 95번째. */
    private static long rank(List<Long> sorted, double percentile) {
        int index = (int) Math.ceil(percentile * sorted.size()) - 1;
        return sorted.get(Math.max(0, Math.min(index, sorted.size() - 1)));
    }

    @Override
    public String toString() {
        return count == 0 ? "표본 없음"
                : "n=%d min=%dms median=%dms p95=%dms max=%dms".formatted(count, min, median, p95, max);
    }
}
