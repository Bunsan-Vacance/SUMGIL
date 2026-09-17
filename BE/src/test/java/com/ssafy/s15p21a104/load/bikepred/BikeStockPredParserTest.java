package com.ssafy.s15p21a104.load.bikepred;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * AI 배치 산출물(`bike_stock_pred_<시각>.csv`) → {@link BikeStockPredRow}.
 * 열은 8개다: {@code rental_id · dow_type · time_slot · exp_bikes · p_empty · p_full · source · prediction_source}.
 * <p>
 * 값은 DB 스케일에 맞춰 줄인다 — {@code exp_bikes} 는 {@code NUMERIC(5,1)}, 확률 둘은 {@code NUMERIC(4,3)} 이라
 * 원천의 배정밀도(4.371794871794871)를 그대로 넣을 수 없다.
 * <p>
 * {@code prediction_source} 는 그 칸이 실제 관측인지 대체값인지를 나타내며({@code observed_avg} /
 * {@code station_time_fallback} / {@code station_global_fallback}) <b>버리지 않고 그대로 싣는다</b> —
 * 대체값을 관측값처럼 보이게 하지 않으려면 읽는 쪽이 구분할 수 있어야 한다.
 * <p>
 * 값을 만들어 넣지 않는다: 숫자 칸이 비었거나 숫자가 아니면 그 행을 만들지 않고 건수를 집계 경고한다.
 */
class BikeStockPredParserTest {

    /** 원천 헤더 순서를 유지한 행 하나. */
    private static Map<String, String> row(String rentalId, String dow, String slot,
                                           String expBikes, String pEmpty, String pFull,
                                           String source, String predictionSource) {
        Map<String, String> r = new LinkedHashMap<>();
        r.put("rental_id", rentalId);
        r.put("dow_type", dow);
        r.put("time_slot", slot);
        r.put("exp_bikes", expBikes);
        r.put("p_empty", pEmpty);
        r.put("p_full", pFull);
        r.put("source", source);
        r.put("prediction_source", predictionSource);
        return r;
    }

    /** 실제 산출물 첫 행 (2026-09-17 01:44 배치). */
    private static Map<String, String> realRow() {
        return row("ST-10", "0", "0", "4.371794871794871", "0.2730769230769231", "0.13846153846153844",
                "avg", "observed_avg");
    }

    private static BikeStockPredParser.Result parse(List<Map<String, String>> rows) {
        var parser = new BikeStockPredParser();
        rows.forEach(parser::accept);
        return parser.finish();
    }

    @Test
    @DisplayName("8열 한 행을 키·값·라벨 그대로 읽는다")
    void readsOneRow() {
        BikeStockPredParser.Result result = parse(List.of(realRow()));

        assertEquals(1, result.rows().size());
        BikeStockPredRow r = result.rows().get(0);
        assertEquals("ST-10", r.rentalId());
        assertEquals(0, r.dowType());
        assertEquals(0, r.timeSlot());
        assertEquals("avg", r.source());
        assertEquals("observed_avg", r.predictionSource());
    }

    @Test
    @DisplayName("원천의 배정밀도를 DB 스케일로 줄인다 — exp_bikes 소수 1자리, 확률 3자리")
    void scalesToDbPrecision() {
        BikeStockPredRow r = parse(List.of(realRow())).rows().get(0);

        assertEquals(new BigDecimal("4.4"), r.expBikes());
        assertEquals(new BigDecimal("0.273"), r.pEmpty());
        assertEquals(new BigDecimal("0.138"), r.pFull());
    }

    @Test
    @DisplayName("prediction_source 가 비면 null 이다 — 빈 문자열을 라벨로 저장하지 않는다")
    void blankPredictionSourceBecomesNull() {
        BikeStockPredRow r = parse(List.of(
                row("ST-10", "0", "0", "4.4", "0.273", "0.138", "avg", ""))).rows().get(0);

        assertNull(r.predictionSource());
    }

    @Test
    @DisplayName("fallback 라벨도 그대로 싣는다 — 대체값이라고 버리지 않는다")
    void keepsFallbackRows() {
        BikeStockPredParser.Result result = parse(List.of(
                row("ST-10", "0", "0", "4.4", "0.273", "0.138", "avg", "observed_avg"),
                row("ST-10", "0", "1", "3.1", "0.400", "0.100", "avg", "station_time_fallback"),
                row("ST-10", "0", "2", "2.0", "0.500", "0.050", "avg", "station_global_fallback")));

        assertEquals(3, result.rows().size());
        assertEquals(List.of("observed_avg", "station_time_fallback", "station_global_fallback"),
                result.rows().stream().map(BikeStockPredRow::predictionSource).toList());
    }

    @Test
    @DisplayName("숫자 칸이 비면 그 행을 만들지 않고 건수를 경고한다 — 값을 채우지 않는다")
    void skipsRowWithBlankNumber() {
        BikeStockPredParser.Result result = parse(List.of(
                realRow(),
                row("ST-11", "0", "0", "", "0.273", "0.138", "avg", "observed_avg")));

        assertEquals(1, result.rows().size());
        assertEquals(1, result.stats().skipped());
        assertTrue(result.rows().stream().noneMatch(r -> r.rentalId().equals("ST-11")));
    }

    @Test
    @DisplayName("요일·슬롯이 숫자가 아니면 건너뛴다")
    void skipsRowWithNonNumericKey() {
        BikeStockPredParser.Result result = parse(List.of(
                realRow(),
                row("ST-12", "평일", "0", "4.4", "0.273", "0.138", "avg", "observed_avg")));

        assertEquals(1, result.rows().size());
        assertEquals(1, result.stats().skipped());
    }

    @Test
    @DisplayName("건너뛴 행이 있으면 건수와 예시를 한 줄로 경고한다")
    void warnsOnceWithCount() {
        var parser = new BikeStockPredParser();
        parser.accept(realRow());
        parser.accept(row("ST-11", "0", "0", "", "0.273", "0.138", "avg", "observed_avg"));
        parser.finish();

        assertEquals(1, parser.warnings().size());
        assertTrue(parser.warnings().get(0).contains("1"), parser.warnings().get(0));
        assertTrue(parser.warnings().get(0).contains("ST-11"), parser.warnings().get(0));
    }

    @Test
    @DisplayName("건너뛴 행이 없으면 경고하지 않는다")
    void noWarningWhenClean() {
        var parser = new BikeStockPredParser();
        parser.accept(realRow());
        parser.finish();

        assertTrue(parser.warnings().isEmpty());
    }

    @Test
    @DisplayName("통계로 원천 행 수·대여소 수·라벨별 건수를 센다")
    void countsStats() {
        BikeStockPredParser.Result result = parse(List.of(
                row("ST-10", "0", "0", "4.4", "0.273", "0.138", "avg", "observed_avg"),
                row("ST-10", "0", "1", "3.1", "0.400", "0.100", "avg", "station_time_fallback"),
                row("ST-11", "0", "0", "2.0", "0.500", "0.050", "avg", "observed_avg")));

        BikeStockPredParser.Stats stats = result.stats();
        assertEquals(3, stats.sourceRows());
        assertEquals(2, stats.stations());
        assertEquals(Map.of("observed_avg", 2, "station_time_fallback", 1), stats.predictionSources());
    }

    @Test
    @DisplayName("필수 열이 없으면 어느 열인지 밝히고 멈춘다 — 원천 스키마가 바뀐 것이다")
    void failsFastOnMissingColumn() {
        Map<String, String> noProbability = new LinkedHashMap<>();
        noProbability.put("rental_id", "ST-10");
        noProbability.put("dow_type", "0");
        noProbability.put("time_slot", "0");
        noProbability.put("exp_bikes", "4.4");
        noProbability.put("source", "avg");

        var parser = new BikeStockPredParser();
        IllegalStateException e = assertThrows(IllegalStateException.class, () -> parser.accept(noProbability));

        assertTrue(e.getMessage().contains("p_empty"), e.getMessage());
        assertTrue(e.getMessage().contains("p_full"), e.getMessage());
    }

    @Test
    @DisplayName("prediction_source 열 자체가 없어도 읽는다 — 라벨은 AI 파이프라인이 나중에 붙인 열이다")
    void predictionSourceColumnIsOptional() {
        Map<String, String> old = new LinkedHashMap<>();
        old.put("rental_id", "ST-10");
        old.put("dow_type", "0");
        old.put("time_slot", "0");
        old.put("exp_bikes", "4.4");
        old.put("p_empty", "0.273");
        old.put("p_full", "0.138");
        old.put("source", "avg");

        BikeStockPredParser.Result result = parse(List.of(old));

        assertEquals(1, result.rows().size());
        assertNull(result.rows().get(0).predictionSource());
    }
}
