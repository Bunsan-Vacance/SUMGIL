package com.ssafy.s15p21a104.consume;

import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

/**
 * 컨슈머 진입점 (S15P21A104-171). 실행:
 * <pre>
 *   SPRING_PROFILES_ACTIVE=local,consume ./gradlew bootRun
 *   SPRING_PROFILES_ACTIVE=local,consume ./gradlew bootRun --args='--consume.dry-run=true'   # 브로커 없이 배선만
 * </pre>
 *
 * <p>실제 소비는 스프링이 관리하는 리스너 컨테이너가 한다. 이 러너는 기동 시 설정을 한 줄로 찍어
 * "무슨 그룹으로 어느 토픽을 어떤 오프셋에서 읽는지" 를 첫 로그에서 확인할 수 있게 한다
 * (수집기의 {@code CollectorRunner} 가 예산 계획을 찍는 것과 같은 자리).
 */
@Slf4j
public class ConsumerRunner implements ApplicationRunner {

    private final ConsumeProperties props;
    private final StatnIdMap statnIds;

    public ConsumerRunner(ConsumeProperties props, StatnIdMap statnIds) {
        this.props = props;
        this.statnIds = statnIds;
    }

    @Override
    public void run(ApplicationArguments args) {
        log.info("컨슈머 — 그룹 {} · 토픽 {} · 오프셋 {} · 배치 최대 {}건 · 브로커 {}",
                props.kafka().groupId(), props.topics(), props.kafka().autoOffsetReset(),
                props.kafka().maxPollRecords(), props.kafka().bootstrapServers());
        log.info("지하철 역 대응표 {}건 · 운영 시간 창 {} (상태 키 판정용, 수집기와 같아야 한다)",
                statnIds.size(), props.subway().window());
        if (props.dryRun()) {
            log.info("dry-run — Kafka 빈을 만들지 않았다. 소비하지 않는다");
        }
    }
}
