package com.ssafy.s15p21a104.collect;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.apache.kafka.clients.admin.NewTopic;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class CollectTopicsTest {

    static CollectProperties props() {
        return new CollectProperties(false, false, null, null, null, null, null,
                new CollectProperties.Source(true, "subway.arrival", Duration.ofSeconds(60), "07:30-13:00", 1_610_612_736L, "k"),
                new CollectProperties.Source(true, "bike.stock", Duration.ofSeconds(120), "07:00-18:00", 1_073_741_824L, "k"),
                new CollectProperties.Weather(true, "weather.nowcast", Duration.ofHours(1), "00:00-24:00", 67_108_864L, "k", 60, 127));
    }

    @Test
    @DisplayName("토픽 3개 · 파티션 1 · 복제본 1 · 보관 48h · 세그먼트 6h/128MiB (S15P21A104-168)")
    void 토픽_3개_정의() {
        List<NewTopic> topics = CollectTopics.define(props());

        assertEquals(List.of("subway.arrival", "bike.stock", "weather.nowcast"), topics.stream().map(NewTopic::name).toList());
        for (NewTopic topic : topics) {
            assertEquals(1, topic.numPartitions(), topic.name());
            assertEquals(1, topic.replicationFactor(), topic.name());
            Map<String, String> config = topic.configs();
            assertEquals("delete", config.get("cleanup.policy"));
            assertEquals(String.valueOf(48L * 60 * 60 * 1000), config.get("retention.ms"), "48시간");
            assertEquals(String.valueOf(6L * 60 * 60 * 1000), config.get("segment.ms"), "6시간 — 이게 없으면 48h 삭제가 안 일어난다");
            assertEquals(String.valueOf(128L * 1024 * 1024), config.get("segment.bytes"));
        }
        assertEquals("1610612736", topics.get(0).configs().get("retention.bytes"), "지하철 1.5GiB");
        assertEquals("1073741824", topics.get(1).configs().get("retention.bytes"), "따릉이 1GiB");
        assertEquals("67108864", topics.get(2).configs().get("retention.bytes"), "날씨 64MiB");
    }

    @Test
    void 기본값이_없으면_48h_6h() {
        CollectProperties.Topics defaults = new CollectProperties.Topics(0, 0);

        assertEquals(48, defaults.retentionHours());
        assertEquals(6, defaults.segmentHours());
    }
}
