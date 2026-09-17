package com.ssafy.s15p21a104.collect.publish;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

/**
 * Kafka 전송. 키는 {@code entity_id}(파티션 1이라 순서에는 영향 없고, 뒤에 파티션을 늘려도 같은 개체는 같은 파티션에 간다).
 * 회차의 모든 이벤트를 비동기로 보낸 뒤 flush 하고 한꺼번에 확인한다 — 건별로 기다리면 3,000건 회차가 몇 분 걸린다.
 */
@Slf4j
public final class KafkaEventPublisher implements EventPublisher {

    private final KafkaTemplate<String, String> template;
    private final CollectEventJson json;
    private final Duration timeout;

    public KafkaEventPublisher(KafkaTemplate<String, String> template, CollectEventJson json, Duration timeout) {
        this.template = template;
        this.json = json;
        this.timeout = timeout;
    }

    @Override
    public int publish(String topic, List<CollectEvent> events) {
        if (events.isEmpty()) {
            return 0;
        }
        List<CompletableFuture<SendResult<String, String>>> futures = new ArrayList<>(events.size());
        for (CollectEvent event : events) {
            futures.add(template.send(topic, event.entityId(), json.write(event)));
        }
        template.flush();

        Instant deadline = Instant.now().plus(timeout);
        int sent = 0;
        int failed = 0;
        Throwable first = null;
        for (CompletableFuture<SendResult<String, String>> future : futures) {
            long remaining = Math.max(1, Duration.between(Instant.now(), deadline).toMillis());
            try {
                future.get(remaining, TimeUnit.MILLISECONDS);
                sent++;
            } catch (ExecutionException | TimeoutException e) {
                failed++;
                if (first == null) {
                    first = e instanceof ExecutionException ee && ee.getCause() != null ? ee.getCause() : e;
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new PublishException("전송 확인 중 인터럽트 (" + topic + ")", sent, events.size() - sent, e);
            }
        }
        if (failed > 0) {
            throw new PublishException("%s 전송 %d/%d건 실패".formatted(topic, failed, events.size()), sent, failed, first);
        }
        return sent;
    }
}
