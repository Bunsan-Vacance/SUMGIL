package com.ssafy.s15p21a104.consume;

import java.time.Duration;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 컨슈머 실행 옵션 (S15P21A104-171). 기본값은 application-consume.yml, 환경변수·명령행 {@code --consume.*} 로 덮는다.
 *
 * @param dryRun true 면 Kafka 빈을 아예 만들지 않는다 — 브로커 없이 배선만 확인할 때 (collect 프로파일과 같은 규칙)
 * @param kafka  브로커 주소·그룹·오프셋 정책
 * @param topics 구독할 토픽. {@code weather.nowcast} 는 기본에서 뺀다 — AI 가 Kafka 에서 직접 읽는지 확답을 못 받았고,
 *               우리가 Redis 에 넣어도 읽는 쪽이 없다. 필요해지면 여기 한 줄 더한다
 * @param subway 지하철 전용 설정
 */
@ConfigurationProperties("consume")
public record ConsumeProperties(boolean dryRun, Kafka kafka, List<String> topics, Subway subway) {

    public ConsumeProperties {
        if (kafka == null) {
            kafka = new Kafka(null, null, null, 0, null);
        }
        if (topics == null || topics.isEmpty()) {
            topics = List.of("subway.arrival", "bike.stock");
        }
        if (subway == null) {
            subway = new Subway(null);
        }
    }

    /**
     * @param bootstrapServers 브로커 주소. 로컬 compose 는 localhost:9092, 클러스터 파드는 kafka:9092
     * @param groupId          BE 반영용 그룹. AI Spark 의 {@code ai-spark} 와 반드시 달라야 한다 —
     *                         같으면 카프카가 메시지를 나눠 줘서 서로 못 받는 이벤트가 생긴다 (kafka.md 5절)
     * @param autoOffsetReset  기본 {@code latest}. 첫 기동에 {@code earliest} 면 보관 48시간치(약 290만 건)를 전부 재생한다
     * @param maxPollRecords   한 번에 가져올 최대 건수. 지하철 회차가 약 3,000건이라 회차가 여러 배치로 잘릴 수 있고,
     *                         반영기는 그것을 전제로 쓰여 있다 ({@link SubwayArrivalApplier})
     * @param pollTimeout      브로커 응답 대기 한계
     */
    public record Kafka(String bootstrapServers, String groupId, String autoOffsetReset, int maxPollRecords,
                        Duration pollTimeout) {
        public Kafka {
            if (bootstrapServers == null || bootstrapServers.isBlank()) {
                bootstrapServers = "localhost:9092";
            }
            if (groupId == null || groupId.isBlank()) {
                groupId = "be-redis";
            }
            if (autoOffsetReset == null || autoOffsetReset.isBlank()) {
                autoOffsetReset = "latest";
            }
            if (maxPollRecords <= 0) {
                maxPollRecords = 500;
            }
            if (pollTimeout == null) {
                pollTimeout = Duration.ofSeconds(3);
            }
        }
    }

    /**
     * @param window 수집기의 운영 시간 창과 <b>같은 값</b>이어야 한다. 상태 키의 {@code outside_window} 판정에 쓴다 —
     *               다르면 수집이 정상인데 "수집 지연" 이라고 하거나 그 반대가 된다.
     *               prod 에서는 수집기와 같은 ConfigMap(be-collector-config)을 물려 한 곳에서 관리한다
     */
    public record Subway(String window) {
        public Subway {
            if (window == null || window.isBlank()) {
                window = "07:30-13:00";
            }
        }
    }
}
