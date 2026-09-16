package com.ssafy.s15p21a104.consume;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.springframework.kafka.listener.ConcurrentMessageListenerContainer;
import org.springframework.test.context.ActiveProfiles;

/**
 * consume 프로파일 배선이 뜨는지 본다 (S15P21A104-171). dry-run 이라 브로커가 필요 없다.
 * DB·Redis 는 다른 {@code @SpringBootTest} 와 같이 필요하다 (컨텍스트를 공유하므로).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE, properties = "consume.dry-run=true")
@ActiveProfiles("consume")
class ConsumeProfileContextTest {

    @Autowired
    ApplicationContext context;

    @Autowired
    ConsumeProperties props;

    @Test
    @DisplayName("설정이 바인딩되고 반영기·디스패처가 붙는다. dry-run 이면 리스너 컨테이너는 없다")
    void 배선이_뜬다() {
        assertEquals("be-redis", props.kafka().groupId(), "AI 의 ai-spark 와 달라야 한다");
        assertEquals("latest", props.kafka().autoOffsetReset(), "earliest 면 첫 기동에 48시간치를 재생한다");
        assertEquals(500, props.kafka().maxPollRecords());
        assertEquals(java.util.List.of("subway.arrival", "bike.stock"), props.topics(),
                "weather.nowcast 는 v1 에서 구독하지 않는다");

        assertEquals(2, context.getBeansOfType(EventApplier.class).size(), "지하철·따릉이 반영기");
        assertEquals(1, context.getBeanNamesForType(BatchDispatcher.class).length);
        assertEquals(1, context.getBeanNamesForType(ConsumerRunner.class).length);
        assertEquals(1, context.getBeanNamesForType(RedisWriter.class).length);
        assertEquals(0, context.getBeanNamesForType(ConcurrentMessageListenerContainer.class).length,
                "dry-run 이면 소비하지 않는다");
    }

    @Test
    @DisplayName("역 대응표를 실제로 읽어 붙인다 — 표가 없으면 기동 때 바로 터진다")
    void 대응표가_붙는다() {
        assertTrue(context.getBean(StatnIdMap.class).size() > 600);
    }
}
