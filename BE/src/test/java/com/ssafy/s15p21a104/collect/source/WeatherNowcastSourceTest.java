package com.ssafy.s15p21a104.collect.source;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.EventIdFactory;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class WeatherNowcastSourceTest {

    private static final OffsetDateTime RUN = OffsetDateTime.parse("2026-09-14T10:50:00+09:00");
    // KST 2026-09-14 10:50:00 → 실황 base 1000 (10:40 이후), 예보 base 1030 (10:45 이후)
    private final Clock clock = Clock.fixed(Instant.parse("2026-09-14T01:50:00Z"), ZoneOffset.UTC);

    private WeatherNowcastSource source(FakeFetcher fetcher) {
        return new WeatherNowcastSource(fetcher, Fixtures.MAPPER, new EventIdFactory(), clock, "a/b=", null, 60, 127);
    }

    @Test
    @DisplayName("실황·예보 두 번 부르고, AI 폴러와 같은 5개 항목만 남긴다")
    void 실황과_예보를_받아_항목_5개만_이벤트로() {
        FakeFetcher fetcher = new FakeFetcher(uri -> uri.toString().contains("getUltraSrtNcst")
                ? Fixtures.resource("/collect/kma-ncst.json") : Fixtures.resource("/collect/kma-fcst.json"));

        PollResult result = source(fetcher).poll(RUN);

        assertEquals(2, result.calls());
        assertEquals(2, fetcher.calls.size());
        assertEquals("https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtNcst"
                + "?authKey=a%2Fb%3D&dataType=JSON&numOfRows=100&pageNo=1&base_date=20260914&base_time=1000&nx=60&ny=127",
                fetcher.calls.get(0).toString(), "인증키는 URL 인코딩, 실황 발표 시각은 10:00");
        assertTrue(fetcher.calls.get(1).toString().contains("getUltraSrtFcst?"));
        assertTrue(fetcher.calls.get(1).toString().contains("base_time=1030"), "예보 발표 시각은 10:30 (10:45 이후라 이번 시각 발표분)");

        // 실황 5 + 예보 5×2시각 = 15
        assertEquals(15, result.events().size());
        Set<String> categories = result.events().stream()
                .map(e -> String.valueOf(e.payload().get("category"))).collect(Collectors.toSet());
        assertEquals(WeatherNowcastSource.CATEGORIES, categories);

        CollectEvent observed = result.events().get(0);
        assertEquals("weather.nowcast", observed.source());
        assertEquals("60:127:PTY", observed.entityId());
        assertEquals(OffsetDateTime.parse("2026-09-14T10:00:00+09:00"), observed.sourceGeneratedAt(), "발표 시각(baseDate+baseTime)");
        assertEquals("0", observed.payload().get("obsrValue"));

        CollectEvent forecast = result.events().get(5);
        assertEquals(OffsetDateTime.parse("2026-09-14T09:30:00+09:00"), forecast.sourceGeneratedAt());
        assertEquals("1000", forecast.payload().get("fcstTime"));
    }

    @Test
    @DisplayName("실황은 매시 정각 + 40분, 예보는 매시 30분 + 15분 뒤부터 그 시각 발표분을 본다")
    void 발표_시각_판단은_AI_폴러와_같다() {
        LocalDateTime t1039 = LocalDateTime.of(2026, 9, 14, 10, 39);
        LocalDateTime t1040 = LocalDateTime.of(2026, 9, 14, 10, 40);
        LocalDateTime t1044 = LocalDateTime.of(2026, 9, 14, 10, 44);
        LocalDateTime t1045 = LocalDateTime.of(2026, 9, 14, 10, 45);
        LocalDateTime t1010 = LocalDateTime.of(2026, 9, 14, 10, 10);

        assertEquals(LocalDateTime.of(2026, 9, 14, 9, 0), WeatherNowcastSource.ncstBase(t1039));
        assertEquals(LocalDateTime.of(2026, 9, 14, 10, 0), WeatherNowcastSource.ncstBase(t1040));
        assertEquals(LocalDateTime.of(2026, 9, 14, 9, 30), WeatherNowcastSource.fcstBase(t1044));
        assertEquals(LocalDateTime.of(2026, 9, 14, 10, 30), WeatherNowcastSource.fcstBase(t1045));
        assertEquals(LocalDateTime.of(2026, 9, 14, 9, 30), WeatherNowcastSource.fcstBase(t1010), "30분 전이면 전 시각 발표분");
        assertEquals(LocalDateTime.of(2026, 9, 13, 23, 0), WeatherNowcastSource.ncstBase(LocalDateTime.of(2026, 9, 14, 0, 10)));
    }

    @Test
    void 데이터_없음_03_은_빈_회차() {
        String noData = Fixtures.MAPPER.writeValueAsString(Map.of("response",
                Map.of("header", Map.of("resultCode", "03", "resultMsg", "NO_DATA"))));

        PollResult result = source(FakeFetcher.always(noData)).poll(RUN);

        assertEquals(2, result.calls());
        assertTrue(result.events().isEmpty());
    }

    @Test
    void 다른_오류_코드는_예외() {
        String denied = Fixtures.MAPPER.writeValueAsString(Map.of("response",
                Map.of("header", Map.of("resultCode", "30", "resultMsg", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"))));

        SourceCallException e = assertThrows(SourceCallException.class, () -> source(FakeFetcher.always(denied)).poll(RUN));

        assertEquals("30", e.code());
    }
}
