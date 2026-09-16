package com.ssafy.s15p21a104.collect.publish;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import java.util.List;

/** 한 회차의 이벤트를 토픽에 넣는다. Kafka 구현과 dry-run(로그만) 구현이 있다. */
public interface EventPublisher {

    /**
     * @return 브로커가 받았다고 확인한 건수
     * @throws PublishException 한 건이라도 실패하면. 성공한 건수는 예외에 들어 있다
     */
    int publish(String topic, List<CollectEvent> events);
}
