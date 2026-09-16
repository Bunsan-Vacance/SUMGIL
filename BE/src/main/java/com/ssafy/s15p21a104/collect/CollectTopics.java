package com.ssafy.s15p21a104.collect;

import java.time.Duration;
import java.util.List;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.common.config.TopicConfig;
import org.springframework.kafka.config.TopicBuilder;

/**
 * 토픽 3개의 정의 (S15P21A104-168). 수집기가 기동할 때 AdminClient 로 만들고, 이미 있으면 설정을 여기 값으로 맞춘다
 * ({@code KafkaAdmin.modifyTopicConfigs}) — 로컬 compose 와 prod 클러스터에 같은 코드가 같은 값을 적용한다.
 *
 * <ul>
 *   <li>파티션 1 · 복제본 1 — 순서 보장(설계서), 브로커 1대</li>
 *   <li>{@code retention.ms} 48h — prod 볼륨 5Gi 에 기본 7일은 넘친다</li>
 *   <li>{@code retention.bytes} 소스별 상한 — 시간 보관이 어긋나도 디스크가 넘치지 않게 하는 둘째 방어선. 파티션 1이라 토픽 상한과 같다</li>
 *   <li>{@code segment.ms} 6h · {@code segment.bytes} 128MiB — 보관 삭제는 <b>닫힌 세그먼트</b>만 지운다. 기본값(7일·1GiB)이면
 *       48h 가 지나도 활성 세그먼트가 안 닫혀 삭제가 일어나지 않는다</li>
 * </ul>
 * 용량 근거는 {@code BE/docs/infra/kafka.md} 토픽 절.
 */
public final class CollectTopics {

    static final long SEGMENT_BYTES = 128L * 1024 * 1024;

    private CollectTopics() {
    }

    public static List<NewTopic> define(CollectProperties props) {
        CollectProperties.Topics policy = props.topics();
        return List.of(
                topic(props.subway().topic(), props.subway().retentionBytes(), policy),
                topic(props.bike().topic(), props.bike().retentionBytes(), policy),
                topic(props.weather().topic(), props.weather().retentionBytes(), policy));
    }

    static NewTopic topic(String name, long retentionBytes, CollectProperties.Topics policy) {
        return TopicBuilder.name(name)
                .partitions(1)
                .replicas(1)
                .config(TopicConfig.CLEANUP_POLICY_CONFIG, TopicConfig.CLEANUP_POLICY_DELETE)
                .config(TopicConfig.RETENTION_MS_CONFIG, String.valueOf(Duration.ofHours(policy.retentionHours()).toMillis()))
                .config(TopicConfig.RETENTION_BYTES_CONFIG, String.valueOf(retentionBytes))
                .config(TopicConfig.SEGMENT_MS_CONFIG, String.valueOf(Duration.ofHours(policy.segmentHours()).toMillis()))
                .config(TopicConfig.SEGMENT_BYTES_CONFIG, String.valueOf(SEGMENT_BYTES))
                .build();
    }
}
