package com.ssafy.s15p21a104.collect;

import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import com.ssafy.s15p21a104.collect.event.EventIdFactory;
import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.collect.http.JdkHttpFetcher;
import com.ssafy.s15p21a104.collect.http.RetryingHttpFetcher;
import com.ssafy.s15p21a104.collect.publish.EventPublisher;
import com.ssafy.s15p21a104.collect.publish.KafkaEventPublisher;
import com.ssafy.s15p21a104.collect.publish.LoggingEventPublisher;
import com.ssafy.s15p21a104.collect.source.BikeStockSource;
import com.ssafy.s15p21a104.collect.source.SourceAdapter;
import com.ssafy.s15p21a104.collect.source.SubwayArrivalSource;
import com.ssafy.s15p21a104.collect.source.WeatherNowcastSource;
import java.net.http.HttpClient;
import java.time.Clock;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import lombok.extern.slf4j.Slf4j;
import org.apache.kafka.clients.admin.AdminClientConfig;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.StringSerializer;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaAdmin;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import tools.jackson.databind.json.JsonMapper;

/**
 * collect 프로파일에서만 활성화되는 배선. API 서버 실행에는 아무 영향이 없다 — Kafka 빈은 여기서만 만들어지고
 * ({@code spring-boot-starter-kafka} 가 아니라 {@code spring-kafka} 만 의존해 자동 구성도 없다), 서버는 외부를 폴링하지 않는다
 * ({@code BE/README.md} 9절).
 *
 * <p>dry-run 이면 Kafka 빈을 아예 만들지 않는다 — 브로커 없이 호출·파싱만 볼 때 기동이 막히지 않게.
 */
@Slf4j
@Configuration
@Profile("collect")
@EnableConfigurationProperties(CollectProperties.class)
public class CollectConfig {

    private static final String DRY_RUN = "collect.dry-run";

    @Bean
    Clock collectClock() {
        return Clock.systemUTC();
    }

    @Bean
    JsonMapper collectJsonMapper() {
        return JsonMapper.builder().build();
    }

    @Bean
    EventIdFactory eventIdFactory() {
        return new EventIdFactory();
    }

    @Bean
    CollectEventJson collectEventJson(JsonMapper collectJsonMapper) {
        return new CollectEventJson(collectJsonMapper);
    }

    @Bean
    HttpClient collectHttpClient(CollectProperties props) {
        return HttpClient.newBuilder()
                .connectTimeout(props.http().connectTimeout())
                .followRedirects(HttpClient.Redirect.NORMAL)
                .build();
    }

    @Bean
    ThreadPoolTaskScheduler collectScheduler() {
        ThreadPoolTaskScheduler scheduler = new ThreadPoolTaskScheduler();
        scheduler.setPoolSize(3);
        scheduler.setThreadNamePrefix("collect-");
        scheduler.setWaitForTasksToCompleteOnShutdown(false);
        return scheduler;
    }

    @Bean
    CollectPlan collectPlan(CollectProperties props, HttpClient collectHttpClient, JsonMapper collectJsonMapper,
                            EventIdFactory eventIdFactory, Clock collectClock, EventPublisher eventPublisher) {
        PollerFactory factory = new PollerFactory(props, collectHttpClient, collectJsonMapper, eventIdFactory,
                collectClock, eventPublisher);
        List<SourcePoller> pollers = new ArrayList<>();
        factory.build("subway", props.subway(), fetcher -> new SubwayArrivalSource(fetcher, collectJsonMapper,
                eventIdFactory, collectClock, props.subway().key(), props.subway().topic())).ifPresent(pollers::add);
        factory.build("bike", props.bike(), fetcher -> new BikeStockSource(fetcher, collectJsonMapper, eventIdFactory,
                collectClock, props.bike().key(), props.bike().topic())).ifPresent(pollers::add);
        CollectProperties.Weather weather = props.weather();
        factory.build("weather", weather.asSource(), fetcher -> new WeatherNowcastSource(fetcher, collectJsonMapper,
                eventIdFactory, collectClock, weather.key(), weather.topic(), weather.nx(), weather.ny()))
                .ifPresent(pollers::add);
        return new CollectPlan(pollers);
    }

    @Bean
    CollectorRunner collectorRunner(CollectProperties props, CollectPlan collectPlan,
                                    ThreadPoolTaskScheduler collectScheduler) {
        return new CollectorRunner(props, collectPlan, collectScheduler);
    }

    // ── Kafka (dry-run 이 아닐 때만) ──────────────────────────────────────────────

    @Bean
    @ConditionalOnProperty(name = DRY_RUN, havingValue = "false", matchIfMissing = true)
    DefaultKafkaProducerFactory<String, String> collectProducerFactory(CollectProperties props) {
        Map<String, Object> config = new HashMap<>();
        config.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, props.kafka().bootstrapServers());
        config.put(ProducerConfig.CLIENT_ID_CONFIG, "sumgil-collector");
        config.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        config.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        // 브로커 1대라 acks=all 도 복제본 1개를 기다리는 것과 같지만, 디스크에 닿은 뒤 확인하겠다는 뜻을 명시한다
        config.put(ProducerConfig.ACKS_CONFIG, "all");
        config.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, true);
        // 회차마다 3,000건이 한 번에 나가므로 잠깐 모아 배치로 보낸다. 지하철 회차 JSON 이 약 3.5MB 라 압축한다 (prod 볼륨 5Gi)
        config.put(ProducerConfig.LINGER_MS_CONFIG, 20);
        config.put(ProducerConfig.BATCH_SIZE_CONFIG, 64 * 1024);
        config.put(ProducerConfig.COMPRESSION_TYPE_CONFIG, "lz4");
        // 브로커가 없으면 메타데이터 대기에서 오래 멈추지 않고 실패로 떨어지게 한다
        config.put(ProducerConfig.MAX_BLOCK_MS_CONFIG, (int) Duration.ofSeconds(10).toMillis());
        return new DefaultKafkaProducerFactory<>(config);
    }

    @Bean
    @ConditionalOnProperty(name = DRY_RUN, havingValue = "false", matchIfMissing = true)
    KafkaTemplate<String, String> collectKafkaTemplate(DefaultKafkaProducerFactory<String, String> collectProducerFactory) {
        return new KafkaTemplate<>(collectProducerFactory);
    }

    @Bean
    @ConditionalOnProperty(name = DRY_RUN, havingValue = "false", matchIfMissing = true)
    KafkaAdmin collectKafkaAdmin(CollectProperties props) {
        KafkaAdmin admin = new KafkaAdmin(Map.of(AdminClientConfig.BOOTSTRAP_SERVERS_CONFIG, props.kafka().bootstrapServers()));
        // 브로커 없이 수집기는 쓸모가 없다 — 기동 시 바로 실패시켜 주소 오설정을 첫 로그에서 잡는다
        admin.setFatalIfBrokerNotAvailable(true);
        // 이미 있는 토픽도 보관 설정을 코드 값으로 맞춘다 (168: 로컬·prod 동일 적용)
        admin.setModifyTopicConfigs(true);
        return admin;
    }

    @Bean
    @ConditionalOnProperty(name = DRY_RUN, havingValue = "false", matchIfMissing = true)
    KafkaAdmin.NewTopics collectTopics(CollectProperties props) {
        return new KafkaAdmin.NewTopics(CollectTopics.define(props).toArray(NewTopic[]::new));
    }

    @Bean
    @ConditionalOnProperty(name = DRY_RUN, havingValue = "false", matchIfMissing = true)
    EventPublisher kafkaEventPublisher(KafkaTemplate<String, String> collectKafkaTemplate, CollectEventJson collectEventJson,
                                       CollectProperties props) {
        return new KafkaEventPublisher(collectKafkaTemplate, collectEventJson, props.kafka().sendTimeout());
    }

    @Bean
    @ConditionalOnProperty(name = DRY_RUN, havingValue = "true")
    EventPublisher loggingEventPublisher(CollectEventJson collectEventJson) {
        return new LoggingEventPublisher(collectEventJson);
    }

    /** 소스 설정 하나를 폴러로 만든다. 비활성이거나 키가 없으면 비운 채로 돌려주고 이유를 로그에 남긴다. */
    private static final class PollerFactory {
        private final CollectProperties props;
        private final HttpClient httpClient;
        private final Clock clock;
        private final EventPublisher publisher;

        PollerFactory(CollectProperties props, HttpClient httpClient, JsonMapper mapper, EventIdFactory ids, Clock clock,
                      EventPublisher publisher) {
            this.props = props;
            this.httpClient = httpClient;
            this.clock = clock;
            this.publisher = publisher;
        }

        java.util.Optional<SourcePoller> build(String name, CollectProperties.Source cfg,
                                               Function<HttpFetcher, SourceAdapter> adapterFactory) {
            if (cfg == null || !cfg.enabled()) {
                log.info("{} 소스 비활성 (collect.{}.enabled=false)", name, name);
                return java.util.Optional.empty();
            }
            if (!cfg.hasKey()) {
                log.warn("{} 소스 인증키가 없어 비활성화한다 (.env.example 의 키 이름 참고)", name);
                return java.util.Optional.empty();
            }
            CallBudget budget = new CallBudget(props.budget().dailyCalls(), clock);
            HttpFetcher fetcher = new RetryingHttpFetcher(
                    new JdkHttpFetcher(httpClient, props.http().readTimeout(), cfg.key()),
                    props.http().maxRetries(), Duration.ofMillis(500), RetryingHttpFetcher.THREAD_SLEEP,
                    budget::recordCall);
            SourceAdapter adapter = adapterFactory.apply(fetcher);
            return java.util.Optional.of(new SourcePoller(adapter, publisher, OperatingWindow.parse(cfg.window()), budget,
                    cfg.interval() == null ? Duration.ofSeconds(60) : cfg.interval(), clock));
        }
    }
}
