package com.ssafy.s15p21a104.domain.bike.eta;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.net.URI;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

/**
 * AI 실시간 재고 예측({@code GET /bike/stations/{id}/eta-stock}) 조회 (S15P21A104-309).
 *
 * <p>AI 는 09-17 부터 v4-weather-final LightGBM 으로 "지금 재고 + N분 뒤 순증감" 을 실시간으로 준다(티켓 160).
 * AI 쪽 계약은 "BE 가 조회 때마다 부르고, 실패하면 자기 DB 배치 통계로 폴백" 이다.
 *
 * <p>규칙은 하나다 — <b>예외를 밖으로 던지지 않고, 모델 값을 못 쓰면 빈 값이다.</b> 빈 값이면 도착 예측은 지금처럼
 * 평균표({@code bike_stock_pred})로 나간다. 버스 혼잡도(297)와 같은 원칙이다.
 */
class BikeEtaReaderTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();
    private static final Instant NOW = Instant.parse("2026-09-23T01:00:00Z"); // 10:00 KST
    private static final Clock FIXED = Clock.fixed(NOW, ZoneOffset.UTC);
    private static final String BASE = "http://100.64.193.109:8000";

    /** 2026-09-23 BE 파드에서 실제로 받은 응답 모양 그대로. */
    private static String body(String source, String pEmpty) {
        return """
                {"rental_id":"ST-1577","eta_minutes":15,"current_stock":1,"predicted_stock":1.4791025719231166,
                 "p_empty":%s,"p_full":0.00006237884228399536,"arrival_dow_type":0,"arrival_time_slot":20,
                 "source":"%s","model_horizon_min":15}
                """.formatted(pEmpty, source);
    }

    /** 부른 주소를 기록하고 정해진 응답(또는 예외)을 돌려주는 가짜. */
    private static final class FakeFetcher implements HttpFetcher {
        final List<URI> calls = new ArrayList<>();
        private final String body;
        private final SourceCallException error;

        FakeFetcher(String body) {
            this.body = body;
            this.error = null;
        }

        FakeFetcher(SourceCallException error) {
            this.body = null;
            this.error = error;
        }

        @Override
        public String get(URI uri) {
            calls.add(uri);
            if (error != null) {
                throw error;
            }
            return body;
        }
    }

    private static BikeEtaReader reader(HttpFetcher fetcher) {
        return new BikeEtaReader(fetcher, MAPPER, FIXED, BASE, 30);
    }

    private static OffsetDateTime inMinutes(long minutes) {
        return OffsetDateTime.ofInstant(NOW, ZoneOffset.ofHours(9)).plusMinutes(minutes);
    }

    @Test
    @DisplayName("309-R1: 도착까지 15분이면 eta_minutes=15 로 부르고, 예측 재고·빈 재고 확률을 응답 모양으로 바꾼다")
    void r1_정상() {
        var fetcher = new FakeFetcher(body("lightgbm", "0.31497916638147594"));

        Optional<BikeEtaStock> stock = reader(fetcher).find("ST-1577", inMinutes(15));

        assertEquals(List.of(URI.create(BASE + "/bike/stations/ST-1577/eta-stock?eta_minutes=15")), fetcher.calls);
        assertTrue(stock.isPresent());
        assertEquals(1, stock.get().predictedBikes());                         // 1.479 → 반올림 1
        assertEquals(1.0 - 0.31497916638147594, stock.get().availabilityProbability(), 1e-12);
        assertEquals(OffsetDateTime.ofInstant(NOW, ZoneOffset.UTC), stock.get().predictedAt()); // 부른 시각
    }

    @Test
    @DisplayName("309-R9: predictedAt 은 밀리초까지만 — FE 가 new Date() 로 읽는데 JS 표준은 소수 3자리까지다(사파리 대비)")
    void r9_밀리초() {
        Clock subMillis = Clock.fixed(Instant.parse("2026-09-23T01:00:00.9573491Z"), ZoneOffset.UTC);
        var reader = new BikeEtaReader(new FakeFetcher(body("lightgbm", "0.3")), MAPPER, subMillis, BASE, 30);

        OffsetDateTime predictedAt = reader.find("ST-1577", inMinutes(15)).orElseThrow().predictedAt();

        assertEquals(OffsetDateTime.parse("2026-09-23T01:00:00.957Z"), predictedAt);
    }

    @Test
    @DisplayName("309-R2: AI 가 404(실시간 재고 없음)·503(모델 장애)·타임아웃이면 빈 값 — 예외를 던지지 않는다")
    void r2_호출_실패() {
        for (SourceCallException e : List.of(
                SourceCallException.http("u", 404),
                SourceCallException.http("u", 503),
                SourceCallException.timeout("u", new java.net.http.HttpTimeoutException("t")))) {
            assertTrue(reader(new FakeFetcher(e)).find("ST-1577", inMinutes(15)).isEmpty(), e.getMessage());
        }
    }

    @Test
    @DisplayName("309-R3: 도착까지 30분을 넘으면 부르지 않는다 — 모델은 30분 앞까지 학습했고 그 너머는 30분으로 근사한다")
    void r3_범위_밖() {
        var far = new FakeFetcher(body("lightgbm", "0.3"));
        var edge = new FakeFetcher(body("lightgbm", "0.3"));

        assertTrue(reader(far).find("ST-1577", inMinutes(31)).isEmpty());
        assertTrue(reader(edge).find("ST-1577", inMinutes(30)).isPresent());
        assertTrue(far.calls.isEmpty());
    }

    @Test
    @DisplayName("309-R4: 이미 지난 도착 시각이면 부르지 않는다")
    void r4_과거() {
        var fetcher = new FakeFetcher(body("lightgbm", "0.3"));

        assertTrue(reader(fetcher).find("ST-1577", inMinutes(-5)).isEmpty());
        assertTrue(fetcher.calls.isEmpty());
    }

    @Test
    @DisplayName("309-R5: 학습에 없던 대여소라 전역 평균(lightgbm_global_fallback)이 오면 빈 값 — 우리 평균표가 대여소별이라 더 낫다")
    void r5_전역_평균() {
        assertTrue(reader(new FakeFetcher(body("lightgbm_global_fallback", "0.3")))
                .find("ST-1577", inMinutes(15)).isEmpty());
    }

    @Test
    @DisplayName("309-R6: p_empty 가 null(분류기 없는 아티팩트)이면 빈 값 — AVAILABLE 응답에 확률을 비워 보내지 않는다")
    void r6_확률_없음() {
        assertTrue(reader(new FakeFetcher(body("lightgbm", "null"))).find("ST-1577", inMinutes(15)).isEmpty());
    }

    @Test
    @DisplayName("309-R7: 응답이 JSON 이 아니면 빈 값")
    void r7_깨진_응답() {
        assertTrue(reader(new FakeFetcher("<html>502 Bad Gateway</html>")).find("ST-1577", inMinutes(15)).isEmpty());
    }

    @Test
    @DisplayName("309-R8: 꺼진 리더(AI 주소 미설정)는 항상 빈 값 — 배포 순서가 뒤집혀도 안 깨진다")
    void r8_비활성() {
        assertTrue(BikeEtaReader.disabled().find("ST-1577", inMinutes(15)).isEmpty());
    }
}
