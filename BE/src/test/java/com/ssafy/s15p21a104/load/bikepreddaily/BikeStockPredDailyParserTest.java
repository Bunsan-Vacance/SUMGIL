package com.ssafy.s15p21a104.load.bikepreddaily;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.load.csv.CsvTable;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 날짜축 예측 CSV → {@link BikeStockPredDailyRow} (S15P21A104-309).
 *
 * <p>lightgbm 산출물 열은 {@code rental_id · pred_date · time_slot · exp_bikes · p_empty · p_full · source}
 * 7개다({@code predictor.py} 의 {@code DATE_OUTPUT_COLS} + {@code source}). avg 에 있는
 * {@code prediction_source} 는 없으므로 선택 열이다.
 */
class BikeStockPredDailyParserTest {

    private static final OffsetDateTime GENERATED = OffsetDateTime.parse("2026-09-23T00:30:00+00:00");

    private static BikeStockPredDailyParser.Result parse(String csv) {
        var parser = new BikeStockPredDailyParser();
        parser.beginFile(GENERATED);
        List<Map<String, String>> rows = CsvTable.parse(csv).rows();
        rows.forEach(parser::accept);
        return parser.finish();
    }

    @Test
    @DisplayName("309-P1: 7열을 읽고 DB 스케일로 줄인다 — prediction_source 가 없으면 null")
    void p1_기본() {
        var result = parse("""
                rental_id,pred_date,time_slot,exp_bikes,p_empty,p_full,source
                ST-10,2026-09-23,17,6.61983,0.06612,0.23456,model
                """);

        BikeStockPredDailyRow row = result.rows().get(0);
        assertEquals("ST-10", row.rentalId());
        assertEquals(LocalDate.of(2026, 9, 23), row.predDate());
        assertEquals(17, row.timeSlot());
        assertEquals("6.6", row.expBikes().toPlainString());
        assertEquals("0.066", row.pEmpty().toPlainString());
        assertEquals("0.235", row.pFull().toPlainString());
        assertEquals("model", row.source());
        assertNull(row.predictionSource());
        assertEquals(GENERATED, row.generatedAt());
    }

    @Test
    @DisplayName("309-P2: 숫자·날짜 칸이 비었거나 형식이 틀리면 행을 만들지 않고 건수를 경고한다 — 값을 채우지 않는다")
    void p2_빈칸_건너뜀() {
        var parser = new BikeStockPredDailyParser();
        parser.beginFile(GENERATED);
        CsvTable.parse("""
                rental_id,pred_date,time_slot,exp_bikes,p_empty,p_full,source
                ST-10,2026-09-23,0,,0.1,0.1,model
                ST-11,09/23/2026,0,1.0,0.1,0.1,model
                ST-12,2026-09-23,0,1.0,0.1,0.1,model
                """).rows().forEach(parser::accept);
        var result = parser.finish();

        assertEquals(1, result.rows().size());
        assertEquals(2, result.stats().skipped());
        assertEquals(1, parser.warnings().size());
        assertTrue(parser.warnings().get(0).contains("2행"), parser.warnings().get(0));
    }

    @Test
    @DisplayName("309-P3: 필수 열이 없으면 첫 행에서 멈춘다 — avg 산출물(dow_type)을 날짜축으로 읽지 않는다")
    void p3_필수열_없음() {
        IllegalStateException e = assertThrows(IllegalStateException.class, () -> parse("""
                rental_id,dow_type,time_slot,exp_bikes,p_empty,p_full,source
                ST-10,0,0,1.0,0.1,0.1,avg
                """));

        assertTrue(e.getMessage().contains("pred_date"), e.getMessage());
    }

    @Test
    @DisplayName("309-P4: 파일을 이어 먹여도 통계는 전체 기준이고, 행마다 그 파일의 generated_at 이 붙는다")
    void p4_여러_파일() {
        var parser = new BikeStockPredDailyParser();
        OffsetDateTime second = GENERATED.plusDays(1);
        parser.beginFile(GENERATED);
        CsvTable.parse("rental_id,pred_date,time_slot,exp_bikes,p_empty,p_full,source\nST-10,2026-09-23,0,1,0.1,0.1,model\n")
                .rows().forEach(parser::accept);
        parser.beginFile(second);
        CsvTable.parse("rental_id,pred_date,time_slot,exp_bikes,p_empty,p_full,source\nST-11,2026-09-24,0,1,0.1,0.1,model\n")
                .rows().forEach(parser::accept);
        var result = parser.finish();

        assertEquals(2, result.stats().sourceRows());
        assertEquals(2, result.stats().stations());
        assertEquals(List.of(LocalDate.of(2026, 9, 23), LocalDate.of(2026, 9, 24)), result.stats().predDates());
        assertEquals(second, result.rows().get(1).generatedAt());
    }
}
