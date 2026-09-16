package com.ssafy.s15p21a104.global.kafka;

import org.apache.kafka.clients.consumer.Consumer;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

/**
 * Kafka 브로커 왕복 확인 (S15P21A104-74 PoC).
 *
 * <p>컨테이너 <b>밖</b>(호스트 JVM)에서 붙는 경로를 검증한다. 컨테이너 안 CLI 로 하는 확인은
 * 브로커가 살아 있다는 것만 말해 주고, 수집기가 실제로 쓸 경로인 외부 리스너
 * ({@code advertised.listeners})가 맞는지는 알려주지 못한다. 그 설정이 틀리면 컨테이너
 * 안에서는 되는데 밖에서만 조용히 타임아웃 난다 — Kafka 로컬 구성에서 가장 흔한 함정이다.
 *
 * <p>스프링 컨텍스트를 띄우지 않는다. PoC 가 확인할 것은 브로커 연결뿐인데
 * {@code @SpringBootTest} 를 쓰면 DB·Redis 까지 필요해져 실패 원인이 흐려진다.
 *
 * <p>{@code KAFKA_BOOTSTRAP_SERVERS} 가 없으면 건너뛴다. CI(be-test)에는 Kafka 서비스가 없고,
 * 이 PoC 때문에 파이프라인을 바꾸지 않기 위해서다. 로컬 실행법은 {@code docs/infra/kafka.md} 참고.
 */
@EnabledIfEnvironmentVariable(
        named = "KAFKA_BOOTSTRAP_SERVERS",
        matches = ".+",
        disabledReason = "Kafka 브로커 주소가 없다. docs/infra/kafka.md 의 기동 절차를 먼저 실행한다")
class KafkaRoundTripIT {

    /** 브로커 응답을 기다리는 한계. 리스너 설정이 틀리면 여기서 걸린다. */
    private static final Duration TIMEOUT = Duration.ofSeconds(15);

    private static final String BOOTSTRAP = System.getenv("KAFKA_BOOTSTRAP_SERVERS");

    @Test
    @DisplayName("호스트에서 토픽에 넣은 메시지를 같은 값으로 꺼낸다")
    void 호스트에서_넣은_메시지를_그대로_꺼낸다() throws Exception {
        // 실행마다 새 토픽을 써서 이전 실행의 잔여 메시지와 섞이지 않게 한다.
        String topic = "poc.roundtrip." + System.nanoTime();
        String key = "150";
        String value = "{\"source\":\"subway\",\"entity_id\":\"150\",\"payload\":{\"arrival_sec\":120}}";

        SendResult<String, String> sent = send(topic, key, value);
        assertNotNull(sent.getRecordMetadata(), "브로커가 레코드 메타데이터를 돌려주지 않았다");

        ConsumerRecord<String, String> received = receiveFirst(topic);

        assertEquals(key, received.key());
        assertEquals(value, received.value());
    }

    private SendResult<String, String> send(String topic, String key, String value) throws Exception {
        Map<String, Object> props = new HashMap<>();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP);
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        // 브로커가 1대뿐이라 acks=all 이어도 복제본 1개를 기다린다. 쓰기가 실제로 디스크에
        // 닿았는지 보려는 것이므로 기본값(1)이 아니라 명시한다.
        props.put(ProducerConfig.ACKS_CONFIG, "all");
        props.put(ProducerConfig.MAX_BLOCK_MS_CONFIG, (int) TIMEOUT.toMillis());

        DefaultKafkaProducerFactory<String, String> factory = new DefaultKafkaProducerFactory<>(props);
        try {
            KafkaTemplate<String, String> template = new KafkaTemplate<>(factory);
            return template.send(topic, key, value).get(TIMEOUT.toSeconds(), TimeUnit.SECONDS);
        } finally {
            factory.destroy();
        }
    }

    private ConsumerRecord<String, String> receiveFirst(String topic) {
        Map<String, Object> props = new HashMap<>();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP);
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        props.put(ConsumerConfig.GROUP_ID_CONFIG, "poc-" + System.nanoTime());
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");

        DefaultKafkaConsumerFactory<String, String> factory = new DefaultKafkaConsumerFactory<>(props);
        // subscribe 대신 assign 을 쓴다. 컨슈머 그룹 리밸런스를 기다리지 않아 결과가 일정하다.
        TopicPartition partition = new TopicPartition(topic, 0);

        try (Consumer<String, String> consumer = factory.createConsumer()) {
            consumer.assign(List.of(partition));
            consumer.seekToBeginning(List.of(partition));

            long deadline = System.nanoTime() + TIMEOUT.toNanos();
            while (System.nanoTime() < deadline) {
                ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(500));
                for (ConsumerRecord<String, String> record : records.records(partition)) {
                    return record;
                }
            }
        }
        throw new AssertionError(
                "%s 안에 %s 에서 메시지를 받지 못했다. 브로커 %s 의 외부 리스너 설정을 확인한다"
                        .formatted(TIMEOUT, topic, BOOTSTRAP));
    }
}
