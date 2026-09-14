package com.ssafy.s15p21a104.collect;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.publish.EventPublisher;
import com.ssafy.s15p21a104.collect.publish.LoggingEventPublisher;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.springframework.kafka.core.KafkaAdmin;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.test.context.ActiveProfiles;

/**
 * collect 프로파일 배선이 뜨는지 본다. 소스는 전부 꺼 두어 외부 API 를 부르지 않고, dry-run 이라 브로커도 필요 없다.
 * DB·Redis 는 다른 {@code @SpringBootTest} 와 같이 필요하다 (컨텍스트를 공유하므로).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE, properties = {
        "collect.dry-run=true",
        "collect.run-once=true",
        "collect.subway.enabled=false",
        "collect.bike.enabled=false",
        "collect.weather.enabled=false"})
@ActiveProfiles("collect")
class CollectProfileContextTest {

    @Autowired
    ApplicationContext context;

    @Autowired
    CollectProperties props;

    @Test
    @DisplayName("collect 프로파일: 설정이 바인딩되고, dry-run 이면 Kafka 빈이 없고 로그 전송기가 붙는다")
    void 배선이_뜬다() {
        assertEquals("subway.arrival", props.subway().topic());
        assertEquals(60, props.subway().interval().toSeconds());
        assertEquals("07:30-13:00", props.subway().window());
        assertEquals(120, props.bike().interval().toSeconds());
        assertEquals(3600, props.weather().interval().toSeconds());
        assertEquals(48, props.topics().retentionHours());
        assertEquals(1000, props.budget().dailyCalls());

        assertTrue(context.getBean(CollectPlan.class).pollers().isEmpty(), "소스를 전부 꺼서 폴러가 없다");
        assertInstanceOf(LoggingEventPublisher.class, context.getBean(EventPublisher.class));
        assertEquals(0, context.getBeanNamesForType(KafkaTemplate.class).length);
        assertEquals(0, context.getBeanNamesForType(KafkaAdmin.class).length);
        assertEquals(1, context.getBeanNamesForType(CollectorRunner.class).length);
    }
}
