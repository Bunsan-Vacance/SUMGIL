package com.ssafy.s15p21a104.consume;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.OperatingWindow;
import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.global.cache.CacheKeys;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 지하철 도착 반영 (S15P21A104-171).
 *
 * <p>핵심은 <b>역 단위 통째 교체</b>다 — 열차별로 부분 갱신하면 이미 떠난 열차가 TTL 까지 남아 "탑승 확인"을 오염시킨다.
 * 다만 한 배치가 회차 하나와 일치한다는 보장이 없어서(max.poll.records 로 잘린다), 같은 회차가 나눠 들어오면 이어붙이고
 * 새 회차가 오면 그때 통째로 바꾼다.
 */
class SubwayArrivalApplierTest {

    /** KST 2026-09-16 10:31:02 */
    private static final Clock CLOCK = Clock.fixed(Instant.parse("2026-09-16T01:31:02Z"), ZoneOffset.UTC);
    private static final OperatingWindow WINDOW = OperatingWindow.parse("10:00-15:30");

    /** 정본 표(statn-id-map.csv)의 실제 행이다 — API statnId 와 우리 역번호가 어긋나는 것을 그대로 쓴다. */
    private static final StatnIdMap MAP = StatnIdMap.parse("""
            statn_id,station_id,line_id,name
            1002000221,221,1002,역삼
            1002000222,222,1002,강남
            1001000133,150,1001,서울
            """);

    private final InMemoryRedisWriter redis = new InMemoryRedisWriter();
    private final SubwayArrivalApplier applier = new SubwayArrivalApplier(redis, MAP, WINDOW, CLOCK);

    private static CollectEvent event(String statnId, String trainNo, String pollRunAt, String recptnDt) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("subwayId", statnId.substring(0, 4));
        row.put("statnId", statnId);
        row.put("statnNm", "역삼");
        row.put("updnLine", "상행");
        row.put("trainLineNm", "성수행 - 강남방면");
        row.put("btrainNo", trainNo);
        row.put("btrainSttus", "일반");
        row.put("bstatnNm", "성수");
        row.put("barvlDt", "120");
        row.put("arvlCd", "2");
        row.put("arvlMsg2", "역삼 출발");
        row.put("arvlMsg3", "역삼");
        row.put("lstcarAt", "0");
        row.put("recptnDt", recptnDt);
        OffsetDateTime run = OffsetDateTime.parse(pollRunAt);
        OffsetDateTime generated = OffsetDateTime.parse(recptnDt);
        return new CollectEvent("id-" + statnId + "-" + trainNo + "-" + pollRunAt, "subway.arrival", statnId,
                generated, run.plusSeconds(1), run, row);
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> trains(String stationId) {
        return (List<Map<String, Object>>) redis.get(CacheKeys.subwayArrival(stationId)).orElseThrow().get("trains");
    }

    @Test
    @DisplayName("statnId 를 우리 역번호로 바꿔 subway:arrival:{station_id} 에 쓴다")
    void 쓴다() {
        ApplyResult result = applier.apply(List.of(
                event("1002000222", "2234", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00")));

        assertEquals(1, result.written());
        assertEquals(0, result.unmapped());
        Map<String, Object> value = redis.get(CacheKeys.subwayArrival("222")).orElseThrow();
        assertEquals("222", value.get("station_id"));
        assertEquals("강남", value.get("station_name"),
                "payload 의 statnNm 이 아니라 정본 표의 역명을 쓴다 — API 는 부역명을 괄호로 붙여 주기도 한다");
        assertEquals("2026-09-16T10:31:00+09:00", value.get("poll_run_at"));
        assertEquals("2026-09-16T10:30:52+09:00", value.get("source_generated_at"));
        assertEquals("2026-09-16T10:31:02+09:00", value.get("written_at"));
        assertEquals(CacheKeys.SUBWAY_ARRIVAL_TTL, redis.ttls.get(CacheKeys.subwayArrival("222")));
    }

    @Test
    @DisplayName("열차 한 대의 필드 — 원본 코드·문구는 그대로 넘기고 eta 는 v1 에서 비운다")
    void 열차_필드() {
        applier.apply(List.of(event("1002000222", "2234", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00")));

        Map<String, Object> train = trains("222").get(0);
        assertEquals("1002", train.get("line_id"));
        assertEquals("상행", train.get("updn_line"));
        assertEquals("성수행 - 강남방면", train.get("train_line_nm"));
        assertEquals("2234", train.get("train_no"));
        assertEquals("일반", train.get("train_sttus"));
        assertEquals("성수", train.get("dest_station_nm"));
        assertEquals(120, train.get("barvl_sec"), "숫자로 준다");
        assertEquals("2", train.get("arvl_cd"));
        assertEquals("역삼 출발", train.get("arvl_msg2"));
        assertEquals("역삼", train.get("arvl_msg3"));
        assertEquals("0", train.get("last_car_at"));
        assertEquals("2026-09-16T10:30:52+09:00", train.get("recptn_dt"));
        assertNull(train.get("eta_at"), "v1 은 도착예정시각을 추정하지 않는다");
        assertEquals("none", train.get("eta_source"));
    }

    @Test
    @DisplayName("새 회차는 역 단위로 통째 교체한다 — 떠난 열차가 남으면 안 된다")
    void 새_회차는_통째_교체() {
        applier.apply(List.of(
                event("1002000222", "2234", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00"),
                event("1002000222", "2236", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00")));
        assertEquals(2, trains("222").size());

        applier.apply(List.of(
                event("1002000222", "2240", "2026-09-16T10:32:00+09:00", "2026-09-16T10:31:52+09:00")));

        List<Map<String, Object>> after = trains("222");
        assertEquals(1, after.size(), "이전 회차의 열차 2대가 남아 있으면 안 된다");
        assertEquals("2240", after.get(0).get("train_no"));
    }

    @Test
    @DisplayName("같은 회차가 배치 둘로 나뉘어 와도 이어붙인다 — 배치 경계에 기대지 않는다")
    void 같은_회차는_이어붙인다() {
        applier.apply(List.of(event("1002000222", "2234", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00")));
        applier.apply(List.of(event("1002000222", "2236", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00")));

        List<Map<String, Object>> after = trains("222");
        assertEquals(2, after.size());
        assertEquals(List.of("2234", "2236"), after.stream().map(t -> t.get("train_no")).toList());
    }

    @Test
    @DisplayName("같은 열차가 두 번 오면 한 번만 남는다 — 페이지 경계 중복")
    void 중복_열차는_한_번만() {
        CollectEvent same = event("1002000222", "2234", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00");

        applier.apply(List.of(same));
        applier.apply(List.of(same));

        assertEquals(1, trains("222").size());
    }

    @Test
    @DisplayName("오래된 회차는 최신을 덮지 않는다")
    void 오래된_회차는_안_덮는다() {
        applier.apply(List.of(event("1002000222", "2240", "2026-09-16T10:32:00+09:00", "2026-09-16T10:31:52+09:00")));

        ApplyResult result = applier.apply(List.of(
                event("1002000222", "2234", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00")));

        assertEquals(0, result.written());
        assertEquals(1, result.skipped());
        assertEquals("2240", trains("222").get(0).get("train_no"));
    }

    @Test
    @DisplayName("대응표에 없는 역은 unmapped 로 세고 쓰지 않는다 — 아무 역에나 쓰지 않는다")
    void 매핑_안_되는_역() {
        ApplyResult result = applier.apply(List.of(
                event("1032000351", "G01", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00")));

        assertEquals(0, result.written());
        assertEquals(1, result.unmapped());
        assertTrue(redis.values.keySet().stream().noneMatch(k -> k.startsWith("subway:arrival:1032")));
    }

    @Test
    @DisplayName("한 배치의 여러 역을 각각 쓴다")
    void 여러_역() {
        ApplyResult result = applier.apply(List.of(
                event("1002000222", "2234", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00"),
                event("1002000221", "2235", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00")));

        assertEquals(2, result.written());
        assertTrue(redis.get(CacheKeys.subwayArrival("222")).isPresent());
        assertTrue(redis.get(CacheKeys.subwayArrival("221")).isPresent());
    }

    @Test
    @DisplayName("반영할 때마다 상태 키를 갱신한다")
    void 상태_키_갱신() {
        applier.apply(List.of(event("1002000222", "2234", "2026-09-16T10:31:00+09:00", "2026-09-16T10:30:52+09:00")));

        Map<String, Object> status = redis.get(CacheKeys.SUBWAY_ARRIVAL_STATUS).orElseThrow();
        assertEquals("ok", status.get("state"));
        assertEquals("2026-09-16T10:31:00+09:00", status.get("last_poll_run_at"));
        assertEquals("10:00-15:30", status.get("window"));
    }

    @Test
    void 빈_배치는_아무것도_안_한다() {
        assertEquals(ApplyResult.NOTHING, applier.apply(List.of()));
        assertEquals(0, redis.writes);
    }
}
