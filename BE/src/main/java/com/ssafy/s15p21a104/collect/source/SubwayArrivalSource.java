package com.ssafy.s15p21a104.collect.source;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.EventIdFactory;
import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.net.URI;
import java.time.Clock;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import tools.jackson.databind.json.JsonMapper;

/**
 * 서울시 지하철 실시간 도착정보 일괄 (OA-15799) → {@code subway.arrival}.
 *
 * <p>일괄 조회는 {@code /{start}/{end}/ALL} 형식만 된다 — 인덱스 없는 {@code /ALL} 은 별도 승인 서비스(ERROR-340).
 * 1회 1,000행 제한(ERROR-336)이라 0/1000, 1000/2000, 2000/3000 … 으로 이어 받고, 응답의 {@code total} 에 닿으면 멈춘다
 * ({@code BE/docs/external/api-survey.md} 2절). 전체는 약 3,000행이라 보통 3회지만 첨두시간에는 3,000 을 넘어
 * (2026-09-14 11:50 실측 3,009) 4회째가 붙는다 — 상한 {@link #MAX_PAGES}. 행은 역 × 방향 × 열차 단위라 이벤트도 그 단위다.
 * 페이지 경계의 행이 양쪽 페이지에 겹쳐 올 수 있는데, 같은 행은 event_id 가 같아 컨슈머가 걸러낸다.
 *
 * <p>{@code entity_id} 는 API 의 {@code statnId}(예: 1009000937) 그대로다. 우리 {@code station.station_id}(서울 역번호)와는
 * 체계가 달라, 대응은 Redis 반영 컨슈머(S15P21A104-171)가 한다. {@code source_generated_at} 은 {@code recptnDt}.
 */
public final class SubwayArrivalSource implements SourceAdapter {

    public static final String DEFAULT_TOPIC = "subway.arrival";
    static final String BASE_URL = "http://swopenapi.seoul.go.kr/api/subway";
    static final int PAGE_SIZE = 1000;
    /** 보통 3회에 끝난다. total 이 3,000 을 넘는 시간대만 4회째가 붙고, 그 이상은 부르지 않는다(예산 보호). */
    static final int USUAL_PAGES = 3;
    static final int MAX_PAGES = 4;
    private static final String OK = "INFO-000";
    private static final String NO_DATA = "INFO-200";
    private static final DateTimeFormatter RECPTN_DT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final HttpFetcher fetcher;
    private final JsonMapper mapper;
    private final EventIdFactory ids;
    private final Clock clock;
    private final String apiKey;
    private final String topic;

    public SubwayArrivalSource(HttpFetcher fetcher, JsonMapper mapper, EventIdFactory ids, Clock clock, String apiKey,
                               String topic) {
        this.fetcher = fetcher;
        this.mapper = mapper;
        this.ids = ids;
        this.clock = clock;
        this.apiKey = apiKey;
        this.topic = topic == null || topic.isBlank() ? DEFAULT_TOPIC : topic;
    }

    @Override
    public String topic() {
        return topic;
    }

    /** 최근 회차에 실제로 든 호출 수. 예산 확인은 이 값으로 한다 — 4회가 붙은 뒤에는 4회 기준으로 남은 예산을 본다. */
    private volatile int lastCalls = USUAL_PAGES;

    @Override
    public int callsPerRun() {
        return Math.max(USUAL_PAGES, lastCalls);
    }

    @Override
    public PollResult poll(OffsetDateTime pollRunAt) {
        List<CollectEvent> events = new ArrayList<>();
        int calls = 0;
        try {
            for (int page = 0; page < MAX_PAGES; page++) {
                int start = page * PAGE_SIZE;
                int end = start + PAGE_SIZE;
                String body = fetcher.get(pageUri(start, end));
                calls++;
                Map<String, Object> root = Json.object(mapper, topic, body);
                // 정상이면 errorMessage 안에, 오류면 최상위에 code/message 가 온다 (probe.mjs parseResponse 와 같은 규칙)
                Object head = root.get("errorMessage") instanceof Map<?, ?> m ? m : root;
                String code = Json.text(Json.at(head, "code"));
                if (NO_DATA.equals(code)) {
                    break;
                }
                if (!OK.equals(code)) {
                    throw SourceCallException.apiError(topic, code, Json.text(Json.at(head, "message")));
                }
                OffsetDateTime ingestedAt = OffsetDateTime.now(clock.withZone(CollectEvent.KST));
                List<Map<String, Object>> rows = Json.rows(root.get("realtimeArrivalList"));
                for (Map<String, Object> row : rows) {
                    events.add(toEvent(row, ingestedAt, pollRunAt));
                }
                Long total = Json.number(Json.at(head, "total"));
                if (rows.size() < PAGE_SIZE || (total != null && end >= total)) {
                    break;
                }
            }
        } finally {
            lastCalls = calls;
        }
        return new PollResult(events, calls);
    }

    URI pageUri(int start, int end) {
        return URI.create("%s/%s/json/realtimeStationArrival/%d/%d/ALL".formatted(BASE_URL, apiKey, start, end));
    }

    private CollectEvent toEvent(Map<String, Object> row, OffsetDateTime ingestedAt, OffsetDateTime pollRunAt) {
        String entityId = Json.text(row.get("statnId"));
        OffsetDateTime generatedAt = parseRecptnDt(Json.text(row.get("recptnDt")));
        return new CollectEvent(ids.eventId(topic, entityId, generatedAt, row), topic, entityId, generatedAt,
                ingestedAt, pollRunAt, row);
    }

    /** {@code "2026-09-08 11:24:09"} (KST) → 오프셋 시각. 비어 있거나 형식이 다르면 null (신선도는 ingested_at 으로 판단). */
    static OffsetDateTime parseRecptnDt(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        try {
            return LocalDateTime.parse(text.trim(), RECPTN_DT).atZone(CollectEvent.KST).toOffsetDateTime();
        } catch (DateTimeParseException e) {
            return null;
        }
    }
}
