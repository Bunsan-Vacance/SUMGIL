package com.ssafy.s15p21a104.collect;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import com.ssafy.s15p21a104.consume.BatchDispatcher;
import com.ssafy.s15p21a104.consume.ConsumeProperties;
import com.ssafy.s15p21a104.consume.ConsumerRunner;
import com.ssafy.s15p21a104.consume.EventApplier;
import org.springframework.kafka.core.KafkaAdmin;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.ConcurrentMessageListenerContainer;

/**
 * API 서버 컨텍스트(collect·consume 프로파일 없음)에는 Kafka 빈도 수집기도 컨슈머도 없어야 한다 —
 * BE/README.md 9절 "서버는 외부를 폴링하지 않는다", 그리고 서버는 Redis 를 읽기만 한다.
 * spring-kafka 를 implementation 으로 올린 뒤에도 이 경계가 지켜지는지 못 박는다.
 */
@SpringBootTest
class KafkaBeansAbsentTest {

    @Autowired
    ApplicationContext context;

    @Test
    @DisplayName("collect 프로파일이 아니면 KafkaTemplate·KafkaAdmin·CollectorRunner 빈이 없다")
    void API_서버_컨텍스트에는_Kafka_빈이_없다() {
        assertEquals(0, context.getBeanNamesForType(KafkaTemplate.class).length);
        assertEquals(0, context.getBeanNamesForType(KafkaAdmin.class).length);
        assertEquals(0, context.getBeanNamesForType(CollectorRunner.class).length);
        assertEquals(0, context.getBeanNamesForType(CollectProperties.class).length);
    }

    @Test
    @DisplayName("consume 프로파일이 아니면 컨슈머 빈이 없다 — API 서버가 Kafka 를 소비하지 않는다 (S15P21A104-171)")
    void API_서버_컨텍스트에는_컨슈머_빈이_없다() {
        assertEquals(0, context.getBeanNamesForType(ConcurrentMessageListenerContainer.class).length);
        assertEquals(0, context.getBeanNamesForType(ConsumerRunner.class).length);
        assertEquals(0, context.getBeanNamesForType(ConsumeProperties.class).length);
        assertEquals(0, context.getBeanNamesForType(BatchDispatcher.class).length);
        assertEquals(0, context.getBeanNamesForType(EventApplier.class).length);
    }
}
