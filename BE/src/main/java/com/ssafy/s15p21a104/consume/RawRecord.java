package com.ssafy.s15p21a104.consume;

/**
 * Kafka 레코드에서 우리가 쓰는 것만 뽑은 것 (S15P21A104-171).
 *
 * <p>{@code ConsumerRecord} 를 그대로 쓰지 않는 이유는 {@link BatchDispatcher} 를 브로커 없이 단위 테스트하기 위해서다
 * (collect 쪽 {@code HttpFetcher} 를 인터페이스로 둔 것과 같은 결).
 *
 * @param topic       토픽 이름. 어느 반영기로 보낼지 정한다
 * @param value       이벤트 JSON (kafka.md 5절 계약)
 * @param timestampMs <b>브로커가 레코드를 append 한 시각.</b> 이벤트의 {@code ingested_at}(수집기가 응답을 받은 시각)과
 *                    이 시각의 차이가 Kafka 가 얹은 비용이고, 이 시각과 {@code written_at} 의 차이가 우리 컨슈머 몫이다
 */
public record RawRecord(String topic, String value, long timestampMs) {
}
