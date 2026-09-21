package com.ssafy.s15p21a104.load.crowdpred;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.load.crowd.CrowdStationCodes;
import com.ssafy.s15p21a104.load.csv.CsvTable;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * AI 배치 산출물 파일을 읽는 원천 (S15P21A104-305).
 *
 * <p>172(재고 예측)와 두 군데가 다르다:
 * <ul>
 *   <li><b>사이드카 meta 가 필수다.</b> {@code generated_at} 이 {@code congestion_pred} 의 NOT NULL
 *       열이고 재적재 판정 근거라, 없으면 넣을 값이 없다. 172 는 경고만 내고 적재했다</li>
 *   <li><b>{@code row_count} 불일치는 오류다.</b> 전송이 끊긴 파일을 넣으면 그날 예측이 반쪽이 된다</li>
 * </ul>
 */
class CsvCongestionPredSourceTest {

    private static final String HEADER =
            "pred_date,line,from_station_no,to_station_no,direction,time_slot,level,data_status,pred_source,predictor_version\n";
    private static final String TWO_ROWS = HEADER
            + "2026-09-20,1호선,150,151,하선,0,1.7,ok,model,lightgbm:x\n"
            + "2026-09-20,1호선,151,150,상선,0,13.6,ok,model,lightgbm:x\n";

    private static CrowdStationCodes codes() {
        return CrowdStationCodes.from(
                rows("src/main/resources/data/subway/conf/station-ids.csv"),
                rows("src/main/resources/data/crowd/conf/crowd-station-aliases.csv"));
    }

    private static List<Map<String, String>> rows(String path) {
        try {
            return CsvTable.parse(Files.readString(Path.of(path), StandardCharsets.UTF_8)).rows();
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    private static Path write(Path dir, String name, String body) throws IOException {
        Path p = dir.resolve(name);
        Files.writeString(p, body, StandardCharsets.UTF_8);
        return p;
    }

    private static void writeMeta(Path dir, String csvName, int rowCount, String generatedAt) throws IOException {
        String base = csvName.substring(0, csvName.length() - ".csv".length());
        write(dir, base + ".meta.json", """
                {"target_date": "2026-09-20", "row_count": %d, "generated_at": "%s"}
                """.formatted(rowCount, generatedAt));
    }

    private static CsvCongestionPredSource source(Path path) {
        return new CsvCongestionPredSource(path, codes());
    }

    @Test
    @DisplayName("305-S1: 파일 경로를 주면 그 파일을 읽고 사이드카에서 generated_at 을 가져온다")
    void s1_파일_지정(@TempDir Path dir) throws IOException {
        Path csv = write(dir, "predictions_2026-09-20_234300.csv", TWO_ROWS);
        writeMeta(dir, "predictions_2026-09-20_234300.csv", 2, "2026-09-20T23:43:00+09:00");

        CongestionPredSource.Loaded loaded = source(csv).read();

        assertEquals(2, loaded.rows().size());
        assertEquals(csv, loaded.origin());
        assertEquals(OffsetDateTime.parse("2026-09-20T23:43:00+09:00"), loaded.meta().generatedAt());
    }

    @Test
    @DisplayName("305-S2: 폴더를 주면 파일명이 가장 늦은 산출물을 고른다 — 배치가 매일 새 파일을 만든다")
    void s2_폴더_최신(@TempDir Path dir) throws IOException {
        write(dir, "predictions_2026-09-19_101500.csv", TWO_ROWS);
        writeMeta(dir, "predictions_2026-09-19_101500.csv", 2, "2026-09-19T10:15:00+09:00");
        Path latest = write(dir, "predictions_2026-09-20_234300.csv", TWO_ROWS);
        writeMeta(dir, "predictions_2026-09-20_234300.csv", 2, "2026-09-20T23:43:00+09:00");

        CongestionPredSource.Loaded loaded = source(dir).read();

        assertEquals(latest, loaded.origin());
        assertEquals(OffsetDateTime.parse("2026-09-20T23:43:00+09:00"), loaded.meta().generatedAt());
    }

    @Test
    @DisplayName("305-S3: 사이드카가 없으면 멈춘다 — generated_at 이 NOT NULL 열이라 넣을 값이 없다")
    void s3_사이드카_없음(@TempDir Path dir) throws IOException {
        Path csv = write(dir, "predictions_2026-09-20_234300.csv", TWO_ROWS);

        IOException e = assertThrows(IOException.class, () -> source(csv).read());
        assertTrue(e.getMessage().contains("meta"), e.getMessage());
    }

    @Test
    @DisplayName("305-S4: row_count 가 실제 행 수와 다르면 멈춘다 — 잘린 파일을 넣지 않는다")
    void s4_행수_불일치(@TempDir Path dir) throws IOException {
        Path csv = write(dir, "predictions_2026-09-20_234300.csv", TWO_ROWS);
        writeMeta(dir, "predictions_2026-09-20_234300.csv", 99, "2026-09-20T23:43:00+09:00");

        IOException e = assertThrows(IOException.class, () -> source(csv).read());
        assertTrue(e.getMessage().contains("99"), e.getMessage());
        assertTrue(e.getMessage().contains("2"), e.getMessage());
    }

    @Test
    @DisplayName("305-S2b: 날짜가 여럿이면 날짜마다 최신 회차를 모두 읽는다 — 배치가 오늘·내일 2일치를 만든다")
    void s2b_날짜별_2일치(@TempDir Path dir) throws IOException {
        // 배치 기본이 --today --tomorrow 라 하루에 파일이 둘 생긴다. 이름만 정렬하면 내일 것만 잡히고
        // 오늘 것이 영영 안 들어간다 — 조회는 오늘 날짜로 하므로 화면이 빈다.
        write(dir, "predictions_2026-09-20_093000.csv", TWO_ROWS);
        writeMeta(dir, "predictions_2026-09-20_093000.csv", 2, "2026-09-21T09:30:00+09:00");
        write(dir, "predictions_2026-09-21_093000.csv", TWO_ROWS.replace("2026-09-20", "2026-09-21"));
        writeMeta(dir, "predictions_2026-09-21_093000.csv", 2, "2026-09-21T09:30:00+09:00");

        CongestionPredSource.Loaded loaded = source(dir).read();

        assertEquals(4, loaded.rows().size(), "두 날짜가 다 들어와야 한다");
        assertEquals(Set.of(LocalDate.of(2026, 9, 20), LocalDate.of(2026, 9, 21)),
                loaded.stats().predDates());
    }

    @Test
    @DisplayName("305-S2c: 같은 날짜가 여러 번이면 그중 최신 회차만 쓴다 — 재생성분이 쌓인다")
    void s2c_같은_날짜_재생성(@TempDir Path dir) throws IOException {
        write(dir, "predictions_2026-09-20_093000.csv", TWO_ROWS);
        writeMeta(dir, "predictions_2026-09-20_093000.csv", 2, "2026-09-20T09:30:00+09:00");
        write(dir, "predictions_2026-09-20_234300.csv", TWO_ROWS);
        writeMeta(dir, "predictions_2026-09-20_234300.csv", 2, "2026-09-20T23:43:00+09:00");

        CongestionPredSource.Loaded loaded = source(dir).read();

        assertEquals(2, loaded.rows().size(), "같은 날짜를 두 번 넣지 않는다");
        assertEquals(OffsetDateTime.parse("2026-09-20T23:43:00+09:00"), loaded.meta().generatedAt(),
                "늦은 회차의 산출 시각을 쓴다");
    }

    @Test
    @DisplayName("305-S5: 폴더에 산출물이 없으면 찾은 경로를 밝힌다")
    void s5_산출물_없음(@TempDir Path dir) {
        IOException e = assertThrows(IOException.class, () -> source(dir).read());
        assertTrue(e.getMessage().contains("predictions_"), e.getMessage());
    }

    @Test
    @DisplayName("305-S6: 사이드카·parquet 은 산출물로 고르지 않는다 — 같은 폴더에 함께 있다")
    void s6_사이드카는_후보_아님(@TempDir Path dir) throws IOException {
        Path csv = write(dir, "predictions_2026-09-20_234300.csv", TWO_ROWS);
        writeMeta(dir, "predictions_2026-09-20_234300.csv", 2, "2026-09-20T23:43:00+09:00");
        write(dir, "predictions_2026-09-20_999999.parquet", "binary");
        write(dir, "predictions_train_2026-09-20_235959.csv", TWO_ROWS);

        assertEquals(csv, source(dir).read().origin());
    }

    @Test
    @DisplayName("305-S7: 사이드카 형식이 깨졌으면 멈춘다 — 조용히 넘기지 않는다")
    void s7_사이드카_깨짐(@TempDir Path dir) throws IOException {
        Path csv = write(dir, "predictions_2026-09-20_234300.csv", TWO_ROWS);
        write(dir, "predictions_2026-09-20_234300.meta.json", "{\"target_date\": \"2026-09-20\"}");

        assertThrows(IOException.class, () -> source(csv).read());
    }

    @Test
    @DisplayName("305-S8: 파서 경고가 그대로 올라온다")
    void s8_경고_전달(@TempDir Path dir) throws IOException {
        Path csv = write(dir, "predictions_2026-09-20_234300.csv",
                HEADER + "2026-09-20,1호선,999999,151,하선,0,1.7,ok,model,lightgbm:x\n");
        writeMeta(dir, "predictions_2026-09-20_234300.csv", 1, "2026-09-20T23:43:00+09:00");

        CongestionPredSource.Loaded loaded = source(csv).read();

        assertTrue(loaded.rows().isEmpty());
        assertTrue(loaded.warnings().stream().anyMatch(w -> w.contains("999999")), () -> "" + loaded.warnings());
    }
}
