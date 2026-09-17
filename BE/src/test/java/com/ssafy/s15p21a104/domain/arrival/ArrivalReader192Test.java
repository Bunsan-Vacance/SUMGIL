package com.ssafy.s15p21a104.domain.arrival;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

/**
 * S15P21A104-192 실시간 도착 조회 RED.
 * Redis 값을 FE용 DTO로 제공하고 4종 상태를 구분한다.
 */
class ArrivalReader192Test {

    private static final Clock FIXED =
            Clock.fixed(Instant.parse("2026-09-18T09:40:00+09:00"), ZoneOffset.of("+09:00"));

    @SuppressWarnings("unchecked")
    private ArrivalReader readerWith(Object arrivalValue, Object statusValue) {
        RedisTemplate<String, Object> template = mock(RedisTemplate.class);
        ValueOperations<String, Object> ops = mock(ValueOperations.class);
        lenient().when(template.opsForValue()).thenReturn(ops);
        lenient().when(ops.get("subway:arrival:222")).thenReturn(arrivalValue);
        lenient().when(ops.get("subway:arrival:status")).thenReturn(statusValue);
        return new ArrivalReader(template, FIXED);
    }

    private static Map<String, Object> train(String trainNo, String etaAt) {
        Map<String, Object> train = new LinkedHashMap<>();
        train.put("line_id", "1002");
        train.put("updn_line", "내선");
        train.put("train_no", trainNo);
        train.put("dest_station_nm", "성수");
        train.put("eta_at", etaAt);
        train.put("eta_source", "msg3");
        train.put("recptn_dt", "2026-09-18T09:39:10+09:00");
        return train;
    }

    private static Map<String, Object> arrivalValue(List<Map<String, Object>> trains) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("trains", trains);
        value.put("updated_at", "2026-09-18T09:39:10+09:00");
        return value;
    }

    private static Map<String, Object> statusValue(String state) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("state", state);
        value.put("last_poll_run_at", "2026-09-18T09:39:00+09:00");
        value.put("window", "05:00-24:00");
        value.put("updated_at", "2026-09-18T09:39:10+09:00");
        return value;
    }

    @Test
    @DisplayName("192-T1: 역별 키 + ok면 실시간 도착 목록을 반환한다")
    void t1_정상_도착목록() {
        ArrivalReader reader = readerWith(
                arrivalValue(List.of(train("001", "2026-09-18T09:42:00+09:00"))),
                statusValue("ok"));

        ArrivalResult result = reader.find("222", "1002");

        assertEquals(ArrivalStatus.LIVE, result.status());
        assertEquals(1, result.trains().size());
        assertEquals("001", result.trains().get(0).trainId());
        assertEquals(
                OffsetDateTime.parse("2026-09-18T09:42:00+09:00"),
                result.trains().get(0).arrivalTime());
    }

    @Test
    @DisplayName("192-T2: 역별 키 없으면 빈 목록 + 상태 구분 (ok면 정보없음)")
    void t2_키없음_ok_정보없음() {
        ArrivalReader reader = readerWith(null, statusValue("ok"));

        ArrivalResult result = reader.find("222", "1002");

        assertEquals(ArrivalStatus.NO_INFO, result.status());
        assertTrue(result.trains().isEmpty());
    }

    @Test
    @DisplayName("192-T3: 운영창 밖이면 OUTSIDE_WINDOW")
    void t3_운영창밖() {
        ArrivalReader reader = readerWith(null, statusValue("outside_window"));

        ArrivalResult result = reader.find("222", "1002");

        assertEquals(ArrivalStatus.OUTSIDE_WINDOW, result.status());
        assertTrue(result.trains().isEmpty());
    }

    @Test
    @DisplayName("192-T4: 수집 지연이면 STALE (오래된 값 정상 반환 금지)")
    void t4_수집지연() {
        ArrivalReader reader = readerWith(
                arrivalValue(List.of(train("001", "2026-09-18T09:42:00+09:00"))),
                statusValue("stale"));

        ArrivalResult result = reader.find("222", "1002");

        assertEquals(ArrivalStatus.STALE, result.status());
        assertTrue(result.trains().isEmpty());
    }

    @Test
    @DisplayName("192-T5: routeId 다르면 해당 노선만 필터한다")
    void t5_routeId필터() {
        Map<String, Object> other = train("002", "2026-09-18T09:45:00+09:00");
        other.put("line_id", "1001");
        ArrivalReader reader = readerWith(
                arrivalValue(List.of(train("001", "2026-09-18T09:42:00+09:00"), other)),
                statusValue("ok"));

        ArrivalResult result = reader.find("222", "1002");

        assertEquals(1, result.trains().size());
        assertEquals("001", result.trains().get(0).trainId());
    }

    @Test
    @DisplayName("192-T6: 깨진 값이면 NO_INFO (예외 없음)")
    void t6_깨진값_정보없음() {
        ArrivalReader reader = readerWith("broken", statusValue("ok"));

        ArrivalResult result = reader.find("222", "1002");

        assertEquals(ArrivalStatus.NO_INFO, result.status());
        assertTrue(result.trains().isEmpty());
    }
}
