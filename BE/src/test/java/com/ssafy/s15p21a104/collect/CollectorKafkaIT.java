package com.ssafy.s15p21a104.collect;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import com.ssafy.s15p21a104.collect.event.EventIdFactory;
import com.ssafy.s15p21a104.collect.publish.KafkaEventPublisher;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.Config;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.admin.TopicDescription;
import org.apache.kafka.clients.consumer.Consumer;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.config.ConfigResource;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaAdmin;
import org.springframework.kafka.core.KafkaTemplate;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;

/**
 * 실제 브로커에 대해 (1) 토픽 3개가 보관 설정과 함께 만들어지고(168), (2) 이벤트가 계약 JSON 으로 들어가는지(169) 본다.
 * {@code KAFKA_BOOTSTRAP_SERVERS} 가 없으면 건너뛴다 (CI 에 브로커 없음 — KafkaRoundTripIT 와 같은 규칙).
 * 스프링 컨텍스트 없이 CollectConfig 의 빈 메서드를 직접 불러 조립한다 — 확인할 것은 브로커와의 약속이지 DB 가 아니다.
 */
@EnabledIfEnvironmentVariable(
        named = "KAFKA_BOOTSTRAP_SERVERS",
        matches = ".+",
        disabledReason = "Kafka 브로커 주소가 없다. docs/infra/kafka.md 의 기동 절차를 먼저 실행한다")
class CollectorKafkaIT {

    private static final Duration TIMEOUT = Duration.ofSeconds(20);
    private static final String BOOTSTRAP = System.getenv("KAFKA_BOOTSTRAP_SERVERS");

    private final CollectConfig config = new CollectConfig();
    private final CollectProperties props = new CollectProperties(false, false, CollectProperties.PUBLISHER_KAFKA,
            new CollectProperties.Kafka(BOOTSTRAP, TIMEOUT), null, null, null,
            CollectTopicsTest.props().subway(), CollectTopicsTest.props().bike(), CollectTopicsTest.props().weather());

    @Test
    @DisplayName("토픽 3개가 파티션 1 · retention.ms 48h · retention.bytes · segment.ms 로 존재한다")
    void 토픽_3개가_보관_설정과_함께_만들어진다() throws Exception {
        KafkaAdmin admin = config.collectKafkaAdmin(props);
        List<NewTopic> topics = CollectTopics.define(props);
        admin.createOrModifyTopics(topics.toArray(NewTopic[]::new));

        try (AdminClient client = AdminClient.create(admin.getConfigurationProperties())) {
            List<String> names = topics.stream().map(NewTopic::name).toList();
            Map<String, TopicDescription> described = client.describeTopics(names).allTopicNames().get();
            for (String name : names) {
                assertEquals(1, described.get(name).partitions().size(), name + " 파티션");
            }
            List<ConfigResource> resources = names.stream().map(n -> new ConfigResource(ConfigResource.Type.TOPIC, n)).toList();
            Map<ConfigResource, Config> configs = client.describeConfigs(resources).all().get();
            for (NewTopic topic : topics) {
                Config actual = configs.get(new ConfigResource(ConfigResource.Type.TOPIC, topic.name()));
                assertEquals("172800000", actual.get("retention.ms").value(), topic.name() + " retention.ms");
                assertEquals(topic.configs().get("retention.bytes"), actual.get("retention.bytes").value(), topic.name() + " retention.bytes");
                assertEquals("21600000", actual.get("segment.ms").value(), topic.name() + " segment.ms");
                assertEquals("134217728", actual.get("segment.bytes").value(), topic.name() + " segment.bytes");
            }
        }
    }

    @Test
    @DisplayName("이벤트가 계약 필드 그대로 bike.stock 에 들어가고 키는 entity_id 다")
    void 이벤트가_계약_JSON_으로_토픽에_들어간다() throws Exception {
        config.collectKafkaAdmin(props).createOrModifyTopics(CollectTopics.define(props).toArray(NewTopic[]::new));
        JsonMapper mapper = config.collectJsonMapper();
        CollectEventJson json = config.collectEventJson(mapper);
        EventIdFactory ids = config.eventIdFactory();
        String topic = props.bike().topic();
        TopicPartition partition = new TopicPartition(topic, 0);

        OffsetDateTime run = OffsetDateTime.parse("2026-09-14T09:00:03+09:00");
        String suffix = String.valueOf(System.nanoTime());
        List<CollectEvent> events = new ArrayList<>();
        for (int i = 0; i < 2; i++) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("stationId", "IT-" + suffix + "-" + i);
            row.put("parkingBikeTotCnt", String.valueOf(i));
            row.put("stationName", null);
            String entityId = "IT-" + suffix + "-" + i;
            events.add(new CollectEvent(ids.eventId(topic, entityId, null, row), topic, entityId, null, run, run, row));
        }

        DefaultKafkaProducerFactory<String, String> producerFactory = config.collectProducerFactory(props);
        try (Consumer<String, String> consumer = consumer()) {
            consumer.assign(List.of(partition));
            long from = consumer.endOffsets(List.of(partition)).get(partition);

            KafkaTemplate<String, String> template = config.collectKafkaTemplate(producerFactory);
            int sent = new KafkaEventPublisher(template, json, TIMEOUT).publish(topic, events);
            assertEquals(2, sent);

            consumer.seek(partition, from);
            List<ConsumerRecord<String, String>> received = receive(consumer, partition, 2);

            assertEquals(events.get(0).entityId(), received.get(0).key(), "키는 entity_id");
            Map<String, Object> body = mapper.readValue(received.get(0).value(), new TypeReference<Map<String, Object>>() {
            });
            assertEquals(List.of("event_id", "source", "entity_id", "source_generated_at", "ingested_at", "poll_run_at",
                    "payload"), List.copyOf(body.keySet()));
            assertEquals(events.get(0).eventId(), body.get("event_id"));
            assertEquals("bike.stock", body.get("source"));
            assertNull(body.get("source_generated_at"));
            assertEquals(run.toString(), body.get("poll_run_at"));
            assertEquals("0", ((Map<?, ?>) body.get("payload")).get("parkingBikeTotCnt"));
            assertTrue(((Map<?, ?>) body.get("payload")).containsKey("stationName"));
        } finally {
            producerFactory.destroy();
        }
    }

    private Consumer<String, String> consumer() {
        Map<String, Object> config = new HashMap<>();
        config.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP);
        config.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        config.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        config.put(ConsumerConfig.GROUP_ID_CONFIG, "collector-it-" + System.nanoTime());
        return new DefaultKafkaConsumerFactory<String, String>(config).createConsumer();
    }

    private static List<ConsumerRecord<String, String>> receive(Consumer<String, String> consumer, TopicPartition partition,
                                                                 int count) {
        List<ConsumerRecord<String, String>> out = new ArrayList<>();
        long deadline = System.nanoTime() + TIMEOUT.toNanos();
        while (out.size() < count && System.nanoTime() < deadline) {
            for (ConsumerRecord<String, String> record : consumer.poll(Duration.ofMillis(500)).records(partition)) {
                out.add(record);
            }
        }
        assertEquals(count, out.size(), "%s 안에 %d건을 받지 못했다".formatted(TIMEOUT, count));
        return out;
    }
}
