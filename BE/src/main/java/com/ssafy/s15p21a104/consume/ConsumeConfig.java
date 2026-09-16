package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.collect.OperatingWindow;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import java.time.Clock;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.listener.ConcurrentMessageListenerContainer;
import org.springframework.kafka.listener.ContainerProperties;
import org.springframework.kafka.listener.BatchMessageListener;
import tools.jackson.databind.json.JsonMapper;

/**
 * consume 프로파일에서만 활성화되는 배선 (S15P21A104-171). API 서버 실행에는 아무 영향이 없다 —
 * Kafka 빈은 여기서만 만들어지고 ({@code spring-boot-starter-kafka} 가 아니라 {@code spring-kafka} 만 의존해 자동 구성이 없다),
 * 서버는 여전히 Redis 를 읽기만 한다. 수집기의 {@code CollectConfig} 와 같은 구조다.
 *
 * <p>dry-run 이면 Kafka 빈을 아예 만들지 않는다 — 브로커 없이 배선만 확인할 때 기동이 막히지 않게.
 */
@Slf4j
@Configuration
@Profile("consume")
@EnableConfigurationProperties(ConsumeProperties.class)
public class ConsumeConfig {

    private static final String DRY_RUN = "consume.dry-run";

    @Bean
    Clock consumeClock() {
        return Clock.systemUTC();
    }

    @Bean
    JsonMapper consumeJsonMapper() {
        return JsonMapper.builder().build();
    }

    @Bean
    CollectEventJson consumeEventJson(JsonMapper consumeJsonMapper) {
        return new CollectEventJson(consumeJsonMapper);
    }

    @Bean
    StatnIdMap statnIdMap() {
        return StatnIdMap.fromClasspath();
    }

    @Bean
    RedisWriter redisWriter(RedisTemplate<String, Object> redisTemplate) {
        return new RedisTemplateWriter(redisTemplate);
    }

    @Bean
    BikeStockApplier bikeStockApplier(RedisWriter redisWriter, Clock consumeClock) {
        return new BikeStockApplier(redisWriter, consumeClock);
    }

    @Bean
    SubwayArrivalApplier subwayArrivalApplier(RedisWriter redisWriter, StatnIdMap statnIdMap,
                                              ConsumeProperties props, Clock consumeClock) {
        return new SubwayArrivalApplier(redisWriter, statnIdMap,
                OperatingWindow.parse(props.subway().window()), consumeClock);
    }

    @Bean
    BatchDispatcher batchDispatcher(List<EventApplier> appliers, CollectEventJson consumeEventJson, Clock consumeClock) {
        return new BatchDispatcher(appliers, consumeEventJson, consumeClock);
    }

    @Bean
    ConsumerRunner consumerRunner(ConsumeProperties props, StatnIdMap statnIdMap) {
        return new ConsumerRunner(props, statnIdMap);
    }

    // ── Kafka (dry-run 이 아닐 때만) ──────────────────────────────────────────────

    @Bean
    @ConditionalOnProperty(name = DRY_RUN, havingValue = "false", matchIfMissing = true)
    DefaultKafkaConsumerFactory<String, String> consumeConsumerFactory(ConsumeProperties props) {
        Map<String, Object> config = new HashMap<>();
        config.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, props.kafka().bootstrapServers());
        config.put(ConsumerConfig.GROUP_ID_CONFIG, props.kafka().groupId());
        config.put(ConsumerConfig.CLIENT_ID_CONFIG, "sumgil-consumer");
        config.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        config.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        // 첫 기동에 earliest 면 보관 48시간치(약 290만 건)를 전부 재생한다. 우리는 "지금 상태" 만 필요하다.
        config.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, props.kafka().autoOffsetReset());
        config.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, props.kafka().maxPollRecords());
        // 반영에 실패해도 오프셋을 넘기지 않도록 수동 커밋(AckMode.BATCH)을 쓴다
        config.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, false);
        return new DefaultKafkaConsumerFactory<>(config);
    }

    @Bean
    @ConditionalOnProperty(name = DRY_RUN, havingValue = "false", matchIfMissing = true)
    ConcurrentMessageListenerContainer<String, String> consumeListenerContainer(
            DefaultKafkaConsumerFactory<String, String> consumeConsumerFactory, ConsumeProperties props,
            BatchDispatcher batchDispatcher) {

        ContainerProperties container = new ContainerProperties(props.topics().toArray(String[]::new));
        container.setPollTimeout(props.kafka().pollTimeout().toMillis());
        container.setAckMode(ContainerProperties.AckMode.BATCH);
        container.setMessageListener((BatchMessageListener<String, String>) records -> {
            List<RawRecord> raw = new ArrayList<>(records.size());
            for (ConsumerRecord<String, String> record : records) {
                raw.add(new RawRecord(record.topic(), record.value(), record.timestamp()));
            }
            DispatchResult result = batchDispatcher.dispatch(raw);
            log.info("배치 {}건 — 반영 {} · 건너뜀 {} · 미매핑 {} · 실패 {} · 무시 {} | produce {} | consume {}",
                    result.total(), result.applied().written(), result.applied().skipped(), result.applied().unmapped(),
                    result.failed(), result.ignored(), result.produce(), result.consume());
        });

        ConcurrentMessageListenerContainer<String, String> listener =
                new ConcurrentMessageListenerContainer<>(consumeConsumerFactory, container);
        // 토픽이 전부 파티션 1이다 (168). 2 이상으로 올려도 나머지 컨슈머는 놀기만 한다 — 늘리려면 파티션부터 늘려야 한다.
        listener.setConcurrency(1);
        return listener;
    }
}
