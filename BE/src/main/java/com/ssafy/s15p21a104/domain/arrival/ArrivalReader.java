package com.ssafy.s15p21a104.domain.arrival;

import com.ssafy.s15p21a104.global.cache.CacheKeys;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Component;

/**
 * {@code subway:arrival:{stationId}} 캐시를 읽어 FE용 도착 후보로 바꾼다(S15P21A104-192).
 * 값 모양은 반영기({@code consume.SubwayArrivalApplier})가 쓰는 것과 같다.
 *
 * <p>서버는 이 캐시를 읽기만 한다. 상태 키({@code subway:arrival:status})와 역별 키
 * 유무를 함께 봐 4종 상태로 가른다:
 * <ul>
 *   <li>역별 키 있음 + ok → LIVE (도착 목록 반환)</li>
 *   <li>역별 키 없음 + ok → NO_INFO (그 역에 정보 없음)</li>
 *   <li>역별 키 없음 + outside_window → OUTSIDE_WINDOW (장애 아님)</li>
 *   <li>stale → STALE (오래된 값 정상 반환 금지 — 목록 비움)</li>
 * </ul>
 * 값이 없거나 형식이 깨졌으면 예외를 던지지 않고 NO_INFO로 다룬다.
 */
@Component
public class ArrivalReader {

    private static final DateTimeFormatter ISO = DateTimeFormatter.ISO_OFFSET_DATE_TIME;

    private final RedisTemplate<String, Object> redisTemplate;
    private final Clock clock;

    public ArrivalReader(RedisTemplate<String, Object> redisTemplate, Clock clock) {
        this.redisTemplate = redisTemplate;
        this.clock = clock;
    }

    /**
     * 역의 실시간 도착 후보를 조회한다.
     *
     * @param stationId 우리 역번호
     * @param routeId 노선 ID. null·빈 문자열이면 전체 노선
     * @return 상태 + 도착 후보
     */
    public ArrivalResult find(String stationId, String routeId) {
        Object statusRaw = redisTemplate.opsForValue().get(CacheKeys.SUBWAY_ARRIVAL_STATUS);
        String state = asText(statusRaw instanceof Map<?, ?> map ? map.get("state") : null);
        Object raw = redisTemplate.opsForValue().get(CacheKeys.subwayArrival(stationId));

        if ("stale".equalsIgnoreCase(state)) {
            return new ArrivalResult(ArrivalStatus.STALE, List.of(), null);
        }
        if ("outside_window".equalsIgnoreCase(state)) {
            return new ArrivalResult(ArrivalStatus.OUTSIDE_WINDOW, List.of(), null);
        }
        if (!(raw instanceof Map<?, ?> map)) {
            return new ArrivalResult(ArrivalStatus.NO_INFO, List.of(), null);
        }
        Object trainsRaw = map.get("trains");
        if (!(trainsRaw instanceof List<?> trains)) {
            return new ArrivalResult(ArrivalStatus.NO_INFO, List.of(), null);
        }
        OffsetDateTime updatedAt = asTime(map.get("updated_at"));
        List<ArrivalResult.ArrivalTrain> result = new ArrayList<>();
        for (Object item : trains) {
            if (!(item instanceof Map<?, ?> train)) {
                continue;
            }
            // routeId 지정 시 line_id 일치만.
            if (routeId != null && !routeId.isEmpty()
                    && !routeId.equals(asText(train.get("line_id")))) {
                continue;
            }
            String trainNo = asText(train.get("train_no"));
            OffsetDateTime etaAt = asTime(train.get("eta_at"));
            if (trainNo == null || etaAt == null) {
                continue;
            }
            String direction = asText(train.get("dest_station_nm"));
            if (direction == null) {
                direction = asText(train.get("train_line_nm"));
            }
            if (direction == null) {
                continue;
            }
            OffsetDateTime recptn = asTime(train.get("recptn_dt"));
            result.add(new ArrivalResult.ArrivalTrain(
                    trainNo, direction, etaAt,
                    recptn != null ? recptn : updatedAt, "LIVE"));
        }
        if (result.isEmpty()) {
            return new ArrivalResult(ArrivalStatus.NO_INFO, List.of(), updatedAt);
        }
        return new ArrivalResult(ArrivalStatus.LIVE, List.copyOf(result), updatedAt);
    }

    private static String asText(Object value) {
        if (value == null) {
            return null;
        }
        String text = value.toString().trim();
        return text.isEmpty() ? null : text;
    }

    private static OffsetDateTime asTime(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return OffsetDateTime.parse(value.toString(), ISO);
        } catch (DateTimeParseException e) {
            return null;
        }
    }
}
