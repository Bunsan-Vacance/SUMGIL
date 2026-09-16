package com.ssafy.s15p21a104.collect.source;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.EventIdFactory;
import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.net.URI;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import tools.jackson.databind.json.JsonMapper;

/**
 * 서울시 공공자전거 실시간 대여정보 bikeList (OA-15493) → {@code bike.stock}.
 *
 * <p>1회 최대 1,000건이라 1/1000, 1001/2000, 2001/3000 세 번에 전체(2,732개소, 2026-09-08)를 받는다.
 * {@code list_total_count} 는 전체가 아니라 요청 페이지의 건수라 끝은 "마지막 페이지가 1,000건 미만"으로 판단한다.
 * 생성시각 필드가 없어 {@code source_generated_at} 은 null 이고 {@code ingested_at} 이 신선도 기준이다.
 * {@code entity_id} 는 {@code stationId}(ST-xxx) — {@code bike_station.rental_id} 와 같은 값이다 (72 결정).
 *
 * <p>실습실 망에서는 {@code openapi.seoul.go.kr:8088} 이 막혀 있어 호출이 안 된다 — 검증은 EC2·핫스팟에서 한다.
 */
public final class BikeStockSource implements SourceAdapter {

    public static final String DEFAULT_TOPIC = "bike.stock";
    static final String BASE_URL = "http://openapi.seoul.go.kr:8088";
    static final int PAGE_SIZE = 1000;
    static final int PAGES = 3;
    private static final String OK = "INFO-000";
    private static final String NO_DATA = "INFO-200";

    private final HttpFetcher fetcher;
    private final JsonMapper mapper;
    private final EventIdFactory ids;
    private final Clock clock;
    private final String apiKey;
    private final String topic;

    public BikeStockSource(HttpFetcher fetcher, JsonMapper mapper, EventIdFactory ids, Clock clock, String apiKey,
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

    @Override
    public int callsPerRun() {
        return PAGES;
    }

    @Override
    public PollResult poll(OffsetDateTime pollRunAt) {
        List<CollectEvent> events = new ArrayList<>();
        int calls = 0;
        for (int page = 0; page < PAGES; page++) {
            int start = page * PAGE_SIZE + 1;
            int end = start + PAGE_SIZE - 1;
            String body = fetcher.get(pageUri(start, end));
            calls++;
            Map<String, Object> root = Json.object(mapper, topic, body);
            // 정상이면 rentBikeStatus.RESULT, 오류면 최상위 RESULT 로 온다
            Object result = Json.at(root, "rentBikeStatus", "RESULT");
            if (result == null) {
                result = root.get("RESULT");
            }
            String code = Json.text(Json.at(result, "CODE"));
            if (NO_DATA.equals(code)) {
                break;
            }
            if (!OK.equals(code)) {
                throw SourceCallException.apiError(topic, code, Json.text(Json.at(result, "MESSAGE")));
            }
            OffsetDateTime ingestedAt = OffsetDateTime.now(clock.withZone(CollectEvent.KST));
            List<Map<String, Object>> rows = Json.rows(Json.at(root, "rentBikeStatus", "row"));
            for (Map<String, Object> row : rows) {
                String entityId = Json.text(row.get("stationId"));
                events.add(new CollectEvent(ids.eventId(topic, entityId, null, row), topic, entityId, null,
                        ingestedAt, pollRunAt, row));
            }
            if (rows.size() < PAGE_SIZE) {
                break;
            }
        }
        return new PollResult(events, calls);
    }

    URI pageUri(int start, int end) {
        return URI.create("%s/%s/json/bikeList/%d/%d/".formatted(BASE_URL, apiKey, start, end));
    }
}
