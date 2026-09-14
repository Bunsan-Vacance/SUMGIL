package com.ssafy.s15p21a104.collect.source;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.EventIdFactory;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class BikeStockSourceTest {

    private static final String KEY = "BIKEKEY";
    private static final OffsetDateTime RUN = OffsetDateTime.parse("2026-09-14T09:00:00+09:00");
    private final Clock clock = Clock.fixed(Instant.parse("2026-09-14T00:00:02Z"), ZoneOffset.UTC);

    private BikeStockSource source(FakeFetcher fetcher) {
        return new BikeStockSource(fetcher, Fixtures.MAPPER, new EventIdFactory(), clock, KEY, null);
    }

    @Test
    @DisplayName("실측 샘플(2026-09-08) → entity_id 는 stationId(ST-xxx), 생성시각은 없고 ingested_at 이 신선도 기준")
    void 샘플_응답을_이벤트로_바꾼다() {
        FakeFetcher fetcher = FakeFetcher.always(Fixtures.sample("bike.json"));

        PollResult result = source(fetcher).poll(RUN);

        assertEquals(1, result.calls());
        assertEquals(20, result.events().size());
        assertEquals("http://openapi.seoul.go.kr:8088/BIKEKEY/json/bikeList/1/1000/", fetcher.calls.get(0).toString());

        CollectEvent first = result.events().get(0);
        assertEquals("bike.stock", first.source());
        assertEquals("ST-4", first.entityId());
        assertNull(first.sourceGeneratedAt());
        assertEquals(OffsetDateTime.parse("2026-09-14T09:00:02+09:00"), first.ingestedAt());
        assertEquals(RUN, first.pollRunAt());
        assertEquals("5", first.payload().get("parkingBikeTotCnt"), "숫자 필드는 문자열 그대로 둔다 (원본 유지)");
        assertEquals("102. 망원역 1번출구 앞", first.payload().get("stationName"));
    }

    @Test
    @DisplayName("1,000건이 꽉 차면 다음 페이지, 미만이면 끝 — list_total_count 는 페이지 건수라 쓰지 않는다")
    void 마지막_페이지가_1000건_미만이면_멈춘다() {
        FakeFetcher fetcher = FakeFetcher.sequence(Fixtures.bikePage(1000, 1), Fixtures.bikePage(1000, 1001),
                Fixtures.bikePage(732, 2001));

        PollResult result = source(fetcher).poll(RUN);

        assertEquals(3, result.calls());
        assertEquals(2732, result.events().size());
        assertEquals(List.of(
                "http://openapi.seoul.go.kr:8088/BIKEKEY/json/bikeList/1/1000/",
                "http://openapi.seoul.go.kr:8088/BIKEKEY/json/bikeList/1001/2000/",
                "http://openapi.seoul.go.kr:8088/BIKEKEY/json/bikeList/2001/3000/"),
                fetcher.calls.stream().map(Object::toString).toList());
    }

    @Test
    void 같은_회차_안_다른_대여소는_event_id_가_다르다() {
        PollResult result = source(FakeFetcher.always(Fixtures.bikePage(3, 1))).poll(RUN);

        assertNotEquals(result.events().get(0).eventId(), result.events().get(1).eventId());
    }

    @Test
    void 오류_코드는_예외() {
        FakeFetcher fetcher = FakeFetcher.always(Fixtures.bikeError("ERROR-500", "서버 오류"));

        SourceCallException e = assertThrows(SourceCallException.class, () -> source(fetcher).poll(RUN));

        assertEquals("ERROR-500", e.code());
    }

    @Test
    void 페이지_범위_밖_INFO_200_은_거기서_끝() {
        FakeFetcher fetcher = FakeFetcher.sequence(Fixtures.bikePage(1000, 1),
                Fixtures.bikeError("INFO-200", "해당하는 데이터가 없습니다."));

        PollResult result = source(fetcher).poll(RUN);

        assertEquals(2, result.calls());
        assertEquals(1000, result.events().size());
    }

    @Test
    void 본문이_JSON_이_아니면_PARSE_예외() {
        FakeFetcher fetcher = FakeFetcher.always("<html>blocked</html>");

        SourceCallException e = assertThrows(SourceCallException.class, () -> source(fetcher).poll(RUN));

        assertEquals(SourceCallException.Kind.PARSE, e.kind());
        assertTrue(e.getMessage().contains("bike.stock"));
    }
}
