package com.ssafy.s15p21a104.collect.source;

import static org.junit.jupiter.api.Assertions.assertEquals;
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

class SubwayArrivalSourceTest {

    private static final String KEY = "SUBWAYKEY";
    private static final OffsetDateTime RUN = OffsetDateTime.parse("2026-09-14T09:00:00+09:00");
    private final Clock clock = Clock.fixed(Instant.parse("2026-09-14T00:00:05Z"), ZoneOffset.UTC);

    private SubwayArrivalSource source(FakeFetcher fetcher) {
        return new SubwayArrivalSource(fetcher, Fixtures.MAPPER, new EventIdFactory(), clock, KEY, null);
    }

    @Test
    @DisplayName("실측 샘플(2026-09-08) 20행 → 이벤트 20건, 1페이지에서 끝난다")
    void 샘플_응답을_이벤트로_바꾼다() {
        FakeFetcher fetcher = FakeFetcher.always(Fixtures.sample("subway.json"));

        PollResult result = source(fetcher).poll(RUN);

        assertEquals(1, result.calls(), "20행 < 1000 이라 다음 페이지를 부르지 않는다");
        assertEquals(20, result.events().size());
        assertEquals("http://swopenapi.seoul.go.kr/api/subway/SUBWAYKEY/json/realtimeStationArrival/0/1000/ALL",
                fetcher.calls.get(0).toString());

        CollectEvent first = result.events().get(0);
        assertEquals("subway.arrival", first.source());
        assertEquals("1009000937", first.entityId(), "entity_id 는 API 의 statnId 그대로");
        assertEquals(OffsetDateTime.parse("2026-09-08T11:24:09+09:00"), first.sourceGeneratedAt(), "recptnDt 를 KST 로");
        assertEquals(OffsetDateTime.parse("2026-09-14T09:00:05+09:00"), first.ingestedAt());
        assertEquals(RUN, first.pollRunAt());
        assertEquals("둔촌오륜", first.payload().get("statnNm"));
        assertTrue(first.payload().containsKey("subwayNm"), "null 필드도 payload 에 남긴다");
        assertNull(first.payload().get("subwayNm"));
        assertEquals(64, first.eventId().length());
    }

    @Test
    @DisplayName("1,000행이 꽉 차면 다음 페이지를 부르고, total 에 닿으면 멈춘다 (전체는 최대 3회)")
    void 페이지를_이어서_받는다() {
        FakeFetcher fetcher = FakeFetcher.sequence(Fixtures.subwayPage(1000, 1500, 1), Fixtures.subwayPage(500, 1500, 1001));

        PollResult result = source(fetcher).poll(RUN);

        assertEquals(2, result.calls());
        assertEquals(1500, result.events().size());
        assertEquals(List.of(
                "http://swopenapi.seoul.go.kr/api/subway/SUBWAYKEY/json/realtimeStationArrival/0/1000/ALL",
                "http://swopenapi.seoul.go.kr/api/subway/SUBWAYKEY/json/realtimeStationArrival/1000/2000/ALL"),
                fetcher.calls.stream().map(Object::toString).toList());
    }

    @Test
    @DisplayName("첨두시간처럼 total 이 3,000 을 넘으면 4회째를 붙이고, 그 뒤 예산 확인은 4회 기준")
    void total_이_3000_을_넘으면_네_번째_페이지를_받는다() {
        FakeFetcher fetcher = FakeFetcher.sequence(Fixtures.subwayPage(1000, 3009, 1), Fixtures.subwayPage(1000, 3009, 1001),
                Fixtures.subwayPage(1000, 3009, 2001), Fixtures.subwayPage(9, 3009, 3001));
        SubwayArrivalSource source = source(fetcher);
        assertEquals(3, source.callsPerRun(), "처음에는 보통값 3");

        PollResult result = source.poll(RUN);

        assertEquals(4, result.calls());
        assertEquals(3009, result.events().size());
        assertEquals("http://swopenapi.seoul.go.kr/api/subway/SUBWAYKEY/json/realtimeStationArrival/3000/4000/ALL",
                fetcher.calls.get(3).toString());
        assertEquals(4, source.callsPerRun(), "다음 회차 예산은 4회로 본다");
    }

    @Test
    void 네_페이지가_전부_차도_다섯_번째는_부르지_않는다() {
        FakeFetcher fetcher = FakeFetcher.sequence(Fixtures.subwayPage(1000, 9000, 1), Fixtures.subwayPage(1000, 9000, 1001),
                Fixtures.subwayPage(1000, 9000, 2001), Fixtures.subwayPage(1000, 9000, 3001));

        PollResult result = source(fetcher).poll(RUN);

        assertEquals(4, result.calls(), "예산 보호 상한");
        assertEquals(4000, result.events().size());
    }

    @Test
    void 세_페이지로_끝나면_예산_기준도_3회로_돌아온다() {
        FakeFetcher fetcher = FakeFetcher.sequence(Fixtures.subwayPage(1000, 2953, 1), Fixtures.subwayPage(1000, 2953, 1001),
                Fixtures.subwayPage(953, 2953, 2001));
        SubwayArrivalSource source = source(fetcher);

        PollResult result = source.poll(RUN);

        assertEquals(3, result.calls());
        assertEquals(2953, result.events().size());
        assertEquals(3, source.callsPerRun());
    }

    @Test
    void 오류_코드는_예외로_올리고_부분_결과를_돌려주지_않는다() {
        FakeFetcher fetcher = FakeFetcher.always(Fixtures.subwayError("ERROR-336", "1000건 초과"));

        SourceCallException e = assertThrows(SourceCallException.class, () -> source(fetcher).poll(RUN));

        assertEquals(SourceCallException.Kind.API_ERROR, e.kind());
        assertEquals("ERROR-336", e.code());
    }

    @Test
    void 데이터_없음_INFO_200_은_빈_회차다() {
        FakeFetcher fetcher = FakeFetcher.always(Fixtures.subwayError("INFO-200", "해당하는 데이터가 없습니다."));

        PollResult result = source(fetcher).poll(RUN);

        assertEquals(1, result.calls());
        assertTrue(result.events().isEmpty());
    }

    @Test
    void 생성시각이_비었거나_형식이_다르면_null() {
        assertNull(SubwayArrivalSource.parseRecptnDt(null));
        assertNull(SubwayArrivalSource.parseRecptnDt(""));
        assertNull(SubwayArrivalSource.parseRecptnDt("2026-09-08T11:24:09"));
        assertEquals(OffsetDateTime.parse("2026-09-08T11:24:09+09:00"),
                SubwayArrivalSource.parseRecptnDt("2026-09-08 11:24:09"));
    }
}
