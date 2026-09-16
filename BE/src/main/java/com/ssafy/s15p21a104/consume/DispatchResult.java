package com.ssafy.s15p21a104.consume;

/**
 * 배치 하나를 처리한 결과 (S15P21A104-171). 회차마다 로그 한 줄로 남긴다.
 *
 * @param applied 반영 결과 합계
 * @param failed  JSON 이 깨져 못 읽은 건수 — 그 건만 버리고 배치는 계속한다
 * @param ignored 반영기가 없는 토픽이라 버린 건수 (예: weather.nowcast 는 AI 가 Kafka 에서 직접 읽는다)
 * @param produce {@code ingested_at → 레코드 timestamp} — Kafka 가 얹은 비용
 * @param consume {@code 레코드 timestamp → written_at} — 우리 컨슈머 처리 시간
 */
public record DispatchResult(ApplyResult applied, int failed, int ignored, LatencyStats produce, LatencyStats consume) {

    public static final DispatchResult NOTHING =
            new DispatchResult(ApplyResult.NOTHING, 0, 0, LatencyStats.EMPTY, LatencyStats.EMPTY);

    public int total() {
        return applied.written() + applied.skipped() + applied.unmapped() + failed + ignored;
    }
}
