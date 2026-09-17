package com.ssafy.s15p21a104.collect.publish;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import java.util.List;
import lombok.extern.slf4j.Slf4j;

/** dry-run 전송기. 브로커 없이 호출·파싱·이벤트 모양만 확인할 때 쓴다. 첫 이벤트 JSON 을 로그로 보여준다. */
@Slf4j
public final class LoggingEventPublisher implements EventPublisher {

    private final CollectEventJson json;

    public LoggingEventPublisher(CollectEventJson json) {
        this.json = json;
    }

    @Override
    public int publish(String topic, List<CollectEvent> events) {
        if (events.isEmpty()) {
            log.info("[dry-run] {} — 이벤트 없음", topic);
            return 0;
        }
        log.info("[dry-run] {} — {}건 (전송 안 함). 첫 이벤트: {}", topic, events.size(), json.write(events.get(0)));
        return events.size();
    }
}
