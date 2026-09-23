package com.ssafy.s15p21a104.load.bikepred;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * 파일 원천. AI 배치가 만든 {@code bike_stock_pred_<시각>.csv} 를 읽는다.
 * <p>
 * 경로로 <b>폴더</b>를 주면 그 안에서 가장 최신 파일을 고른다 — 배치가 매일 새 파일을 이름에 시각을 붙여 만들기 때문에
 * 적재 명령이 날짜마다 달라지면 안 된다. 최신 판정은 파일명 정렬로 하며, 이는 AI 서빙 API 가 같은 폴더에서
 * 최신 파일을 고르는 방식과 같다(`AI/app/BIKE/service.py` 의 `sorted(glob)`). 양쪽이 다르게 고르면 안 된다.
 * <p>
 * 옆에 있는 {@code .meta.json} 의 {@code rows} 와 실제 읽은 행 수가 다르면 경고한다 — 파일이 잘렸거나
 * 전송이 끊긴 것을 적재 전에 잡는다.
 */
class CsvBikeStockPredSourceTest {

    private static final String HEADER =
            "rental_id,dow_type,time_slot,exp_bikes,p_empty,p_full,source,prediction_source\n";
    private static final String THREE_ROWS = HEADER
            + "ST-10,0,0,4.4,0.273,0.138,avg,observed_avg\n"
            + "ST-10,0,1,3.1,0.400,0.100,avg,station_time_fallback\n"
            + "ST-11,0,0,2.0,0.500,0.050,avg,observed_avg\n";

    private static Path writeCsv(Path dir, String name, String body) throws IOException {
        Path p = dir.resolve(name);
        Files.writeString(p, body, StandardCharsets.UTF_8);
        return p;
    }

    @Test
    @DisplayName("파일 경로를 주면 그 파일을 읽는다")
    void readsGivenFile(@TempDir Path dir) throws IOException {
        Path csv = writeCsv(dir, "bike_stock_pred_20260917-014432.csv", THREE_ROWS);

        BikeStockPredSource.Loaded loaded = new CsvBikeStockPredSource(csv).read();

        assertEquals(3, loaded.rows().size());
        assertEquals(csv, loaded.origin());
        assertEquals(2, loaded.stats().stations());
    }

    @Test
    @DisplayName("폴더 경로를 주면 파일명이 가장 늦은 산출물을 고른다 — 배치가 매일 새 파일을 만든다")
    void picksLatestFileInDirectory(@TempDir Path dir) throws IOException {
        writeCsv(dir, "bike_stock_pred_20260915-003838.csv", HEADER + "ST-1,0,0,1.0,0.100,0.010,avg,observed_avg\n");
        Path latest = writeCsv(dir, "bike_stock_pred_20260917-014432.csv", THREE_ROWS);

        BikeStockPredSource.Loaded loaded = new CsvBikeStockPredSource(dir).read();

        assertEquals(latest, loaded.origin());
        assertEquals(3, loaded.rows().size());
    }

    @Test
    @DisplayName("폴더에서 bike_stock_pred_*.csv 가 아닌 파일은 고르지 않는다 — parquet·meta 가 같이 있다")
    void ignoresNonCsvSiblings(@TempDir Path dir) throws IOException {
        writeCsv(dir, "bike_stock_pred_20260918-999999.parquet", "이건 아님");
        writeCsv(dir, "bike_stock_pred_20260918-999999.meta.json", "{}");
        Path csv = writeCsv(dir, "bike_stock_pred_20260917-014432.csv", THREE_ROWS);

        assertEquals(csv, new CsvBikeStockPredSource(dir).read().origin());
    }

    @Test
    @DisplayName("meta.json 의 rows 와 실제 행 수가 다르면 경고한다 — 파일이 잘린 것을 잡는다")
    void warnsWhenMetaRowCountDiffers(@TempDir Path dir) throws IOException {
        writeCsv(dir, "bike_stock_pred_20260917-014432.csv", THREE_ROWS);
        writeCsv(dir, "bike_stock_pred_20260917-014432.meta.json",
                "{\n \"source\": \"avg\",\n \"rows\": 406656,\n \"stations\": 2824\n}\n");

        BikeStockPredSource.Loaded loaded = new CsvBikeStockPredSource(dir).read();

        assertEquals(1, loaded.warnings().size());
        assertTrue(loaded.warnings().get(0).contains("406656"), loaded.warnings().get(0));
        assertTrue(loaded.warnings().get(0).contains("3"), loaded.warnings().get(0));
    }

    @Test
    @DisplayName("meta.json 의 rows 와 실제 행 수가 같으면 경고하지 않는다")
    void noWarningWhenMetaMatches(@TempDir Path dir) throws IOException {
        writeCsv(dir, "bike_stock_pred_20260917-014432.csv", THREE_ROWS);
        writeCsv(dir, "bike_stock_pred_20260917-014432.meta.json", "{\"rows\": 3, \"stations\": 2}\n");

        assertTrue(new CsvBikeStockPredSource(dir).read().warnings().isEmpty());
    }

    @Test
    @DisplayName("meta.json 이 없으면 경고 없이 읽는다 — 대조는 있을 때만 한다")
    void metaIsOptional(@TempDir Path dir) throws IOException {
        writeCsv(dir, "bike_stock_pred_20260917-014432.csv", THREE_ROWS);

        BikeStockPredSource.Loaded loaded = new CsvBikeStockPredSource(dir).read();

        assertEquals(3, loaded.rows().size());
        assertTrue(loaded.warnings().isEmpty());
    }

    @Test
    @DisplayName("meta.json 이 깨져 있으면 경고만 하고 적재는 계속한다 — 대조 실패가 적재를 막지는 않는다")
    void brokenMetaWarnsButLoads(@TempDir Path dir) throws IOException {
        writeCsv(dir, "bike_stock_pred_20260917-014432.csv", THREE_ROWS);
        writeCsv(dir, "bike_stock_pred_20260917-014432.meta.json", "이건 JSON 이 아니다");

        BikeStockPredSource.Loaded loaded = new CsvBikeStockPredSource(dir).read();

        assertEquals(3, loaded.rows().size());
        assertEquals(1, loaded.warnings().size());
    }

    @Test
    @DisplayName("309-G1: 사이드카가 source=model 인 파일은 고르지 않는다 — lightgbm 산출물도 같은 파일명 규칙이다")
    void skipsModelArtifactWithSameNamingRule(@TempDir Path dir) throws IOException {
        // AI batch_predict.py 는 예측기와 무관하게 bike_stock_pred_<시각>.csv 로 짓는다. lightgbm 파일이 더 늦게
        // 생기면 파일명 최신으로 그걸 집어 dow_type 이 없다며 avg 적재 전체가 멈춘다.
        Path avg = writeCsv(dir, "bike_stock_pred_20260917-014432.csv", THREE_ROWS);
        writeCsv(dir, "bike_stock_pred_20260923-003000.csv",
                "rental_id,pred_date,time_slot,exp_bikes,p_empty,p_full,source\nST-10,2026-09-23,0,4.4,0.2,0.1,model\n");
        writeCsv(dir, "bike_stock_pred_20260923-003000.meta.json",
                "{\n \"source\": \"model\",\n \"target_date\": \"2026-09-23\",\n \"rows\": 1\n}\n");

        BikeStockPredSource.Loaded loaded = new CsvBikeStockPredSource(dir).read();

        assertEquals(avg, loaded.origin());
        assertEquals(3, loaded.rows().size());
    }

    @Test
    @DisplayName("파일이 없으면 찾은 경로를 밝히고 멈춘다")
    void missingFileFailsWithPath(@TempDir Path dir) {
        Path missing = dir.resolve("bike_stock_pred_20260101-000000.csv");

        IOException e = assertThrows(IOException.class, () -> new CsvBikeStockPredSource(missing).read());

        assertTrue(e.getMessage().contains("bike_stock_pred_20260101-000000.csv"), e.getMessage());
    }

    @Test
    @DisplayName("폴더가 비어 있으면 폴더 경로를 밝히고 멈춘다")
    void emptyDirectoryFailsWithPath(@TempDir Path dir) {
        IOException e = assertThrows(IOException.class, () -> new CsvBikeStockPredSource(dir).read());

        assertTrue(e.getMessage().contains(dir.toString()), e.getMessage());
    }

    @Test
    @DisplayName("BOM 과 CRLF 가 있어도 읽는다 — 원천이 어떤 도구를 거쳐 올지 모른다")
    void readsBomAndCrlf(@TempDir Path dir) throws IOException {
        writeCsv(dir, "bike_stock_pred_20260917-014432.csv",
                "﻿" + THREE_ROWS.replace("\n", "\r\n"));

        assertEquals(3, new CsvBikeStockPredSource(dir).read().rows().size());
    }
}
