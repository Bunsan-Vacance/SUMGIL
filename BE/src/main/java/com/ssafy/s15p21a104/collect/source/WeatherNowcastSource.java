package com.ssafy.s15p21a104.collect.source;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.EventIdFactory;
import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.json.JsonMapper;

/**
 * 기상청 API허브 초단기실황(getUltraSrtNcst)·초단기예보(getUltraSrtFcst) → {@code weather.nowcast}.
 *
 * <p>AI 폴러({@code AI/DATA_ENGINE/collect/weather_nowcast.py})가 하는 것과 같은 항목을 같은 규칙으로 받는다 —
 * 격자 서울 종로구 nx=60 ny=127, 항목 T1H(기온)·RN1(1시간 강수량)·REH(습도)·WSD(풍속)·PTY(강수형태),
 * 발표 시각 판단(실황 매시 정각 + 40분, 예보 매시 30분 + 15분 뒤부터 안정). 이 수집기가 대신 받으면 AI 컨슈머 부담이 줄고
 * 금요일까지 두 경로를 비교한 뒤 폴러를 내릴지 정한다 (2026-09-14 결정).
 *
 * <p>API허브(authKey)는 공공데이터포털(serviceKey)과 별개 시스템이라 키를 섞어 쓰면 안 된다.
 * 응답 항목 하나가 이벤트 하나다. {@code entity_id} 는 {@code nx:ny:category}, {@code source_generated_at} 은 발표 시각(baseDate+baseTime).
 * 실황 항목은 {@code obsrValue}, 예보 항목은 {@code fcstDate·fcstTime·fcstValue} 를 가지므로 payload 만 보고도 구분된다.
 */
public final class WeatherNowcastSource implements SourceAdapter {

    public static final String DEFAULT_TOPIC = "weather.nowcast";
    static final String BASE_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0";
    static final String NCST = "getUltraSrtNcst";
    static final String FCST = "getUltraSrtFcst";
    static final Set<String> CATEGORIES = Set.of("T1H", "RN1", "REH", "WSD", "PTY");
    private static final String OK = "00";
    private static final String NO_DATA = "03";
    private static final DateTimeFormatter DATE = DateTimeFormatter.ofPattern("yyyyMMdd");
    private static final DateTimeFormatter TIME = DateTimeFormatter.ofPattern("HHmm");

    private final HttpFetcher fetcher;
    private final JsonMapper mapper;
    private final EventIdFactory ids;
    private final Clock clock;
    private final String apiKey;
    private final String topic;
    private final int nx;
    private final int ny;

    public WeatherNowcastSource(HttpFetcher fetcher, JsonMapper mapper, EventIdFactory ids, Clock clock, String apiKey,
                                String topic, int nx, int ny) {
        this.fetcher = fetcher;
        this.mapper = mapper;
        this.ids = ids;
        this.clock = clock;
        this.apiKey = apiKey;
        this.topic = topic == null || topic.isBlank() ? DEFAULT_TOPIC : topic;
        this.nx = nx;
        this.ny = ny;
    }

    @Override
    public String topic() {
        return topic;
    }

    @Override
    public int callsPerRun() {
        return 2;
    }

    @Override
    public PollResult poll(OffsetDateTime pollRunAt) {
        LocalDateTime now = LocalDateTime.now(clock.withZone(CollectEvent.KST));
        List<CollectEvent> events = new ArrayList<>();
        events.addAll(fetch(NCST, ncstBase(now), pollRunAt));
        events.addAll(fetch(FCST, fcstBase(now), pollRunAt));
        return new PollResult(events, 2);
    }

    private List<CollectEvent> fetch(String endpoint, LocalDateTime base, OffsetDateTime pollRunAt) {
        String body = fetcher.get(uri(endpoint, base));
        Map<String, Object> root = Json.object(mapper, topic, body);
        Object header = Json.at(root, "response", "header");
        String code = Json.text(Json.at(header, "resultCode"));
        if (NO_DATA.equals(code)) {
            return List.of();
        }
        if (!OK.equals(code)) {
            throw SourceCallException.apiError(topic, code, Json.text(Json.at(header, "resultMsg")));
        }
        OffsetDateTime ingestedAt = OffsetDateTime.now(clock.withZone(CollectEvent.KST));
        List<CollectEvent> events = new ArrayList<>();
        for (Map<String, Object> item : Json.rows(Json.at(root, "response", "body", "items", "item"))) {
            String category = Json.text(item.get("category"));
            if (category == null || !CATEGORIES.contains(category)) {
                continue;
            }
            String entityId = nx + ":" + ny + ":" + category;
            OffsetDateTime generatedAt = parseBase(Json.text(item.get("baseDate")), Json.text(item.get("baseTime")));
            events.add(new CollectEvent(ids.eventId(topic, entityId, generatedAt, item), topic, entityId, generatedAt,
                    ingestedAt, pollRunAt, item));
        }
        return events;
    }

    URI uri(String endpoint, LocalDateTime base) {
        String query = "authKey=%s&dataType=JSON&numOfRows=100&pageNo=1&base_date=%s&base_time=%s&nx=%d&ny=%d"
                .formatted(URLEncoder.encode(apiKey, StandardCharsets.UTF_8), DATE.format(base), TIME.format(base),
                        nx, ny);
        return URI.create(BASE_URL + "/" + endpoint + "?" + query);
    }

    /** 초단기실황: 매시 정각 발표, 40분 뒤부터 안정. 그 전이면 한 시간 전 발표분을 본다. */
    static LocalDateTime ncstBase(LocalDateTime now) {
        LocalDateTime candidate = now.truncatedTo(ChronoUnit.HOURS);
        if (now.isBefore(candidate.plus(Duration.ofMinutes(40)))) {
            candidate = candidate.minusHours(1);
        }
        return candidate;
    }

    /** 초단기예보: 매시 30분 발표, 15분 뒤(= 45분)부터 안정. 그 전이면 한 시간 전 발표분을 본다. */
    static LocalDateTime fcstBase(LocalDateTime now) {
        LocalDateTime candidate = now.truncatedTo(ChronoUnit.HOURS).plusMinutes(30);
        if (now.isBefore(candidate.plus(Duration.ofMinutes(15)))) {
            candidate = candidate.minusHours(1);
        }
        return candidate;
    }

    static OffsetDateTime parseBase(String date, String time) {
        if (date == null || time == null) {
            return null;
        }
        try {
            return LocalDateTime.parse(date.trim() + time.trim(), DateTimeFormatter.ofPattern("yyyyMMddHHmm"))
                    .atZone(CollectEvent.KST).toOffsetDateTime();
        } catch (DateTimeParseException e) {
            return null;
        }
    }
}
