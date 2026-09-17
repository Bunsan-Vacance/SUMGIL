package com.ssafy.s15p21a104.load.bus;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 버스 배차간격 수집 CSV(`seoul-bus-headway_<날짜>.csv`) → {@link BusHeadwayRow}.
 * 열은 {@code busRouteId · rtNm · term · firstTm · lastTm · routeType · observedStId · mkTm} 8개이고,
 * 이 로더는 그중 {@code busRouteId}·{@code term} 만 쓴다.
 * <p>
 * <b>{@code term} 0 은 NULL 이다.</b> 원천에서 0 은 "배차 0분" 이 아니라 "그 시각에 운행 중이 아니라 모른다" 는 뜻이다.
 * 0 을 그대로 넣으면 그래프가 대기시간 0초로 계산해 그 노선이 무조건 최단 경로로 뽑힌다.
 * <p>
 * 첫차·막차({@code firstTm}·{@code lastTm})는 CSV 에 있지만 <b>적재하지 않는다</b> — 9일 간격 두 관측에서
 * 12/14 노선이 몇 분씩 달라져(2026-09-08 vs 09-17) 정적 표에 넣으면 그날부터 낡는다. 열은 나중에 쓸 수 있게 남겨 둔다.
 */
class BusHeadwayParserTest {

    private static Map<String, String> row(String routeId, String term) {
        Map<String, String> r = new LinkedHashMap<>();
        r.put("busRouteId", routeId);
        r.put("rtNm", "741");
        r.put("term", term);
        r.put("firstTm", "20260908040100");
        r.put("lastTm", "20260908225100");
        r.put("routeType", "3");
        r.put("observedStId", "111000012");
        r.put("mkTm", "2026-09-08 11:10:10.0");
        return r;
    }

    private static BusHeadwayParser.Result parse(List<Map<String, String>> rows) {
        var parser = new BusHeadwayParser();
        return parser.parse(rows);
    }

    @Test
    @DisplayName("노선 ID 와 배차간격을 읽는다")
    void readsRouteAndHeadway() {
        BusHeadwayParser.Result result = parse(List.of(row("123000010", "10")));

        assertEquals(1, result.rows().size());
        BusHeadwayRow r = result.rows().get(0);
        assertEquals("123000010", r.routeId());
        assertEquals(10, r.headwayMin());
    }

    @Test
    @DisplayName("term 0 은 NULL 이다 — 배차 0분이 아니라 운행 중이 아니라는 뜻이다")
    void zeroTermBecomesNull() {
        BusHeadwayRow r = parse(List.of(row("123000010", "0"))).rows().get(0);

        assertNull(r.headwayMin());
    }

    @Test
    @DisplayName("term 이 비어 있어도 NULL 이다")
    void blankTermBecomesNull() {
        assertNull(parse(List.of(row("123000010", ""))).rows().get(0).headwayMin());
    }

    @Test
    @DisplayName("term 이 숫자가 아니면 행을 만들지 않고 건수를 경고한다")
    void skipsNonNumericTerm() {
        var parser = new BusHeadwayParser();
        BusHeadwayParser.Result result = parser.parse(List.of(row("123000010", "10"), row("100100587", "없음")));

        assertEquals(1, result.rows().size());
        assertEquals(1, result.stats().skipped());
        assertEquals(1, parser.warnings().size());
        assertTrue(parser.warnings().get(0).contains("100100587"), parser.warnings().get(0));
    }

    @Test
    @DisplayName("노선 ID 가 비면 건너뛴다 — 대상을 식별할 수 없다")
    void skipsBlankRouteId() {
        BusHeadwayParser.Result result = parse(List.of(row("", "10")));

        assertTrue(result.rows().isEmpty());
        assertEquals(1, result.stats().skipped());
    }

    @Test
    @DisplayName("음수는 그대로 넘긴다 — 값 규약 위반은 검증기가 막는다")
    void negativeTermIsPassedThrough() {
        assertEquals(-5, parse(List.of(row("123000010", "-5"))).rows().get(0).headwayMin());
    }

    @Test
    @DisplayName("통계로 원천 행 수·배차간격이 있는 노선 수를 센다")
    void countsStats() {
        BusHeadwayParser.Result result = parse(List.of(
                row("123000010", "10"), row("100100587", "16"), row("100000028", "0")));

        assertEquals(3, result.stats().sourceRows());
        assertEquals(2, result.stats().withHeadway());
        assertEquals(0, result.stats().skipped());
    }

    @Test
    @DisplayName("건너뛴 행이 없으면 경고하지 않는다")
    void noWarningWhenClean() {
        var parser = new BusHeadwayParser();
        parser.parse(List.of(row("123000010", "10")));

        assertTrue(parser.warnings().isEmpty());
    }

    @Test
    @DisplayName("필수 열이 없으면 어느 열인지 밝히고 멈춘다 — 수집 스크립트가 바뀐 것이다")
    void failsFastOnMissingColumn() {
        Map<String, String> noTerm = new LinkedHashMap<>();
        noTerm.put("busRouteId", "123000010");
        noTerm.put("rtNm", "741");

        var parser = new BusHeadwayParser();
        IllegalStateException e = assertThrows(IllegalStateException.class, () -> parser.parse(List.of(noTerm)));

        assertTrue(e.getMessage().contains("term"), e.getMessage());
    }

    @Test
    @DisplayName("같은 노선이 두 번 나오면 뒤엣것을 무시한다 — 수집 스크립트가 이미 노선당 한 행으로 합친다")
    void keepsFirstOfDuplicateRoute() {
        BusHeadwayParser.Result result = parse(List.of(row("123000010", "10"), row("123000010", "99")));

        assertEquals(1, result.rows().size());
        assertEquals(10, result.rows().get(0).headwayMin());
    }
}
