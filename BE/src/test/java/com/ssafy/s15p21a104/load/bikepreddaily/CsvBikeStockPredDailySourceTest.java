package com.ssafy.s15p21a104.load.bikepreddaily;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * 따릉이 날짜축 예측(lightgbm) 산출물을 읽는 원천 (S15P21A104-309).
 *
 * <p>AI {@code batch_predict.py} 는 예측기와 무관하게 파일명을 {@code bike_stock_pred_<생성시각>.csv} 로
 * 짓는다. 날짜축인지는 <b>헤더({@code pred_date})와 사이드카 {@code target_date}</b> 로만 구분된다 — 그래서
 * 대상 날짜는 파일명이 아니라 사이드카에서 읽는다(혼잡도 305 는 파일명에 날짜가 있었다).
 *
 * <p>혼잡도 로더와 같은 규칙:
 * <ul>
 *   <li>사이드카 필수 — {@code generated_at} 이 NOT NULL 열이고 {@code predictedAt} 으로 나간다</li>
 *   <li>같은 대상 날짜가 여러 회차면 {@code generated_at} 이 가장 늦은 것 하나</li>
 *   <li>{@code rows} 합이 실제 행 수와 다르면 오류 — 잘린 파일을 넣지 않는다</li>
 * </ul>
 */
class CsvBikeStockPredDailySourceTest {

    private static final String HEADER = "rental_id,pred_date,time_slot,exp_bikes,p_empty,p_full,source\n";

    private static String rowsFor(String date, String exp) {
        return HEADER
                + "ST-10," + date + ",0," + exp + ",0.273,0.138,model\n"
                + "ST-10," + date + ",1,3.1,0.400,0.100,model\n";
    }

    private static Path write(Path dir, String name, String body) throws IOException {
        Path p = dir.resolve(name);
        Files.writeString(p, body, StandardCharsets.UTF_8);
        return p;
    }

    /** AI batch_predict.py 가 lightgbm 으로 돌 때 쓰는 사이드카 모양 그대로. */
    private static void writeMeta(Path dir, String csvName, int rows, String targetDate, String generatedAt)
            throws IOException {
        String base = csvName.substring(0, csvName.length() - ".csv".length());
        write(dir, base + ".meta.json", """
                {
                 "source": "model",
                 "artifact": "multisource-v1_20260914-1937",
                 "predictor_version": "lightgbm:multisource-v1_20260914-1937",
                 "target_date": "%s",
                 "rows": %d,
                 "stations": 1,
                 "generated_at": "%s"
                }
                """.formatted(targetDate, rows, generatedAt));
    }

    @Test
    @DisplayName("309-S1: 파일을 주면 읽고, 행마다 사이드카 generated_at 을 붙인다")
    void s1_파일_지정(@TempDir Path dir) throws IOException {
        Path csv = write(dir, "bike_stock_pred_20260923-003000.csv", rowsFor("2026-09-23", "4.4"));
        writeMeta(dir, "bike_stock_pred_20260923-003000.csv", 2, "2026-09-23", "2026-09-23T00:30:00+00:00");

        BikeStockPredDailySource.Loaded loaded = new CsvBikeStockPredDailySource(csv).read();

        assertEquals(2, loaded.rows().size());
        assertEquals(List.of(csv), loaded.origins());
        assertEquals(LocalDate.of(2026, 9, 23), loaded.rows().get(0).predDate());
        assertEquals(OffsetDateTime.parse("2026-09-23T00:30:00+00:00"), loaded.rows().get(0).generatedAt());
    }

    @Test
    @DisplayName("309-S2: 같은 대상 날짜가 두 회차면 generated_at 이 늦은 쪽 하나만 — 파일명 순서와 무관하다")
    void s2_같은_날짜_최신_회차(@TempDir Path dir) throws IOException {
        // 파일명은 앞이지만 generated_at 이 더 늦다 — 파일명 시각에는 생성 날짜가 없어 이름으로 못 가른다(304).
        Path later = write(dir, "bike_stock_pred_20260923-003000.csv", rowsFor("2026-09-24", "9.9"));
        writeMeta(dir, "bike_stock_pred_20260923-003000.csv", 2, "2026-09-24", "2026-09-24T00:30:00+00:00");
        write(dir, "bike_stock_pred_20260923-235900.csv", rowsFor("2026-09-24", "1.0"));
        writeMeta(dir, "bike_stock_pred_20260923-235900.csv", 2, "2026-09-24", "2026-09-23T23:59:00+00:00");

        BikeStockPredDailySource.Loaded loaded = new CsvBikeStockPredDailySource(dir).read();

        assertEquals(List.of(later), loaded.origins());
        assertEquals(2, loaded.rows().size());
        assertEquals("9.9", loaded.rows().get(0).expBikes().toPlainString());
    }

    @Test
    @DisplayName("309-S3: 대상 날짜가 둘이면 둘 다 날짜 순으로 읽는다 — 오늘·내일치를 함께 받는다")
    void s3_날짜_둘(@TempDir Path dir) throws IOException {
        Path tomorrow = write(dir, "bike_stock_pred_20260923-003100.csv", rowsFor("2026-09-24", "5.0"));
        writeMeta(dir, "bike_stock_pred_20260923-003100.csv", 2, "2026-09-24", "2026-09-23T00:31:00+00:00");
        Path today = write(dir, "bike_stock_pred_20260923-003000.csv", rowsFor("2026-09-23", "4.0"));
        writeMeta(dir, "bike_stock_pred_20260923-003000.csv", 2, "2026-09-23", "2026-09-23T00:30:00+00:00");

        BikeStockPredDailySource.Loaded loaded = new CsvBikeStockPredDailySource(dir).read();

        assertEquals(List.of(today, tomorrow), loaded.origins());
        assertEquals(4, loaded.rows().size());
        assertEquals(List.of(LocalDate.of(2026, 9, 23), LocalDate.of(2026, 9, 24)), loaded.stats().predDates());
    }

    @Test
    @DisplayName("309-S4: 사이드카가 없으면 멈춘다 — generated_at 은 넣을 값이 없으면 안 되는 열이다")
    void s4_사이드카_없음(@TempDir Path dir) throws IOException {
        Path csv = write(dir, "bike_stock_pred_20260923-003000.csv", rowsFor("2026-09-23", "4.4"));

        IOException e = assertThrows(IOException.class, () -> new CsvBikeStockPredDailySource(csv).read());

        assertTrue(e.getMessage().contains("meta"), e.getMessage());
    }

    @Test
    @DisplayName("309-S5: 사이드카 rows 합과 실제 행 수가 다르면 멈춘다 — 잘린 파일을 넣지 않는다")
    void s5_행수_불일치(@TempDir Path dir) throws IOException {
        write(dir, "bike_stock_pred_20260923-003000.csv", rowsFor("2026-09-23", "4.4"));
        writeMeta(dir, "bike_stock_pred_20260923-003000.csv", 135552, "2026-09-23", "2026-09-23T00:30:00+00:00");

        IOException e = assertThrows(IOException.class, () -> new CsvBikeStockPredDailySource(dir).read());

        assertTrue(e.getMessage().contains("135552"), e.getMessage());
    }

    @Test
    @DisplayName("309-S6: target_date 가 없는 사이드카(avg 산출물)는 고르지 않는다 — 같은 파일명 규칙이다")
    void s6_avg_산출물_무시(@TempDir Path dir) throws IOException {
        write(dir, "bike_stock_pred_20260923-030000.csv",
                "rental_id,dow_type,time_slot,exp_bikes,p_empty,p_full,source\nST-10,0,0,4.4,0.2,0.1,avg\n");
        write(dir, "bike_stock_pred_20260923-030000.meta.json",
                "{\"source\": \"avg\", \"target_date\": null, \"rows\": 1, \"generated_at\": \"2026-09-23T03:00:00+00:00\"}");
        Path daily = write(dir, "bike_stock_pred_20260923-003000.csv", rowsFor("2026-09-23", "4.4"));
        writeMeta(dir, "bike_stock_pred_20260923-003000.csv", 2, "2026-09-23", "2026-09-23T00:30:00+00:00");

        BikeStockPredDailySource.Loaded loaded = new CsvBikeStockPredDailySource(dir).read();

        assertEquals(List.of(daily), loaded.origins());
    }

    /*
     * 날짜축 표는 비어 있어도 되는 표다 — 조회가 평균표로 떨어진다. AI 가 날짜축 산출물을 내기 전에도 CronJob 은
     * 매일 돌고, 이때 실패로 멈추면 매일 가짜 실패 기록이 쌓여 앞 두 적재(bikepred·crowdpred)의 진짜 실패가 묻힌다.
     * 그래서 "산출물이 아직 없음" 은 경고 + 빈 결과로 넘기고, 산출물이 있는데 깨진 것(S4·S5)만 멈춘다.
     */

    @Test
    @DisplayName("309-S7: 폴더에 날짜축 산출물이 없으면 빈 결과로 넘기고 폴더 경로를 경고한다 — 비어도 되는 표다")
    void s7_빈_폴더(@TempDir Path dir) throws IOException {
        BikeStockPredDailySource.Loaded loaded = new CsvBikeStockPredDailySource(dir).read();

        assertTrue(loaded.rows().isEmpty());
        assertTrue(loaded.origins().isEmpty());
        assertEquals(1, loaded.warnings().size());
        assertTrue(loaded.warnings().get(0).contains(dir.toString()), loaded.warnings().get(0));
    }

    @Test
    @DisplayName("309-S8: 폴더 자체가 없어도 빈 결과로 넘긴다 — AI 가 아직 serving-daily 를 만들지 않은 상태다")
    void s8_폴더_없음(@TempDir Path dir) throws IOException {
        Path missing = dir.resolve("serving-daily");

        BikeStockPredDailySource.Loaded loaded = new CsvBikeStockPredDailySource(missing).read();

        assertTrue(loaded.rows().isEmpty());
        assertEquals(1, loaded.warnings().size());
    }

    @Test
    @DisplayName("309-S9: 파일을 직접 지정했는데 없으면 멈춘다 — 사람이 고른 경로가 틀린 것이다")
    void s9_지정_파일_없음(@TempDir Path dir) {
        Path missing = dir.resolve("bike_stock_pred_20260923-003000.csv");

        IOException e = assertThrows(IOException.class, () -> new CsvBikeStockPredDailySource(missing).read());

        assertTrue(e.getMessage().contains(missing.toString()), e.getMessage());
    }
}
