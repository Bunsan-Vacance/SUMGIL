package com.ssafy.s15p21a104.load.crowdpred;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.load.crowd.CrowdStationCodes;
import com.ssafy.s15p21a104.load.csv.CsvTable;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * AI CROWD 배치 CSV → {@link CongestionPredRow} (S15P21A104-305).
 *
 * <p>입력은 2026-09-21 에 AI 에게서 받은 실물 샘플(278행, 모든 분기 포함)과 인라인 행이다.
 * 하루치 전체(21,684행)는 저장소에 넣지 않는다 — 매일 바뀌고 배치가 다시 만든다.
 */
class CongestionPredParserTest {

    /** 실제 conf 파일로 만든 매핑. 역번호 체계가 바뀌면 여기서 먼저 깨진다. */
    private static CrowdStationCodes codes() {
        return CrowdStationCodes.from(
                csv("src/main/resources/data/subway/conf/station-ids.csv"),
                csv("src/main/resources/data/crowd/conf/crowd-station-aliases.csv"));
    }

    private static List<Map<String, String>> csv(String path) {
        try {
            return CsvTable.parse(Files.readString(Path.of(path), StandardCharsets.UTF_8)).rows();
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** Gradle 테스트의 작업 디렉터리는 BE/ 다. */
    private static List<Map<String, String>> sample() {
        return csv("docs/external/samples/predictions_2026-09-20_278rows.csv");
    }

    private static Map<String, String> row(String line, String from, String to, String direction,
                                           String slot, String level, String status, String source,
                                           String version) {
        Map<String, String> r = new LinkedHashMap<>();
        r.put("pred_date", "2026-09-20");
        r.put("line", line);
        r.put("from_station_no", from);
        r.put("to_station_no", to);
        r.put("direction", direction);
        r.put("time_slot", slot);
        r.put("level", level);
        r.put("data_status", status);
        r.put("pred_source", source);
        r.put("predictor_version", version);
        return r;
    }

    private static Map<String, String> ok(String line, String from, String to) {
        return row(line, from, to, "상선", "17", "42.5", "ok", "model", "lightgbm:x");
    }

    private static CongestionPredParser.Result parse(List<Map<String, String>> rows) {
        var parser = new CongestionPredParser(codes());
        rows.forEach(parser::accept);
        return parser.finish();
    }

    @Test
    @DisplayName("305-P1: 실물 샘플 278행이 모두 행이 된다 — 모르는 역번호·노선이 없다")
    void p1_실물_샘플() {
        var parser = new CongestionPredParser(codes());
        sample().forEach(parser::accept);
        CongestionPredParser.Result result = parser.finish();

        assertEquals(278, result.stats().sourceRows());
        assertEquals(278, result.rows().size(), "한 행도 버리지 않는다");
        assertEquals(0, result.stats().unknownStations());
        assertEquals(0, result.stats().unknownLines());
        assertTrue(parser.warnings().isEmpty(), () -> "경고: " + parser.warnings());
    }

    @Test
    @DisplayName("305-P2: 역번호를 우리 station_id 로 바꾼다 — 환승역은 최솟값으로 합쳐진다")
    void p2_역번호_매핑() {
        // 4호선 서울역 426 → 150(1호선 코드가 더 작다) · 9호선 종합운동장 4130 → 218
        CongestionPredParser.Result r = parse(List.of(
                ok("4호선", "426", "427"),
                ok("9호선", "4130", "4131")));

        assertEquals("150", r.rows().get(0).fromStationId());
        assertEquals("218", r.rows().get(1).fromStationId());
    }

    @Test
    @DisplayName("305-P3: 노선 이름을 line_id 로 바꾼다")
    void p3_노선_매핑() {
        CongestionPredParser.Result r = parse(List.of(ok("9호선", "4126", "4127")));

        assertEquals("1009", r.rows().get(0).lineId());
    }

    @Test
    @DisplayName("305-P4: level 빈 칸은 null 이다 — 0 으로 채우지 않는다")
    void p4_결측은_null() {
        CongestionPredParser.Result r = parse(List.of(
                row("1호선", "150", "151", "하선", "0", "", "no_calibration", "model", "lightgbm:x")));

        assertNull(r.rows().get(0).level());
        assertEquals("no_calibration", r.rows().get(0).dataStatus());
    }

    @Test
    @DisplayName("305-P5: level 은 소수 1자리로 줄인다 — NUMERIC(5,1)")
    void p5_스케일() {
        CongestionPredParser.Result r = parse(List.of(
                row("1호선", "150", "151", "하선", "0", "1.7229770879488375", "ok", "model", "lightgbm:x")));

        assertEquals(new BigDecimal("1.7"), r.rows().get(0).level());
    }

    @Test
    @DisplayName("305-P6: 100 을 넘는 값도 그대로 보존한다 — 상한이 없다")
    void p6_100_초과() {
        CongestionPredParser.Result r = parse(List.of(
                row("2호선", "226", "227", "외선", "17", "164.4", "ok", "model", "lightgbm:x")));

        assertEquals(new BigDecimal("164.4"), r.rows().get(0).level());
    }

    @Test
    @DisplayName("305-P7: 모르는 역번호는 행을 만들지 않고 집계 경고한다")
    void p7_모르는_역번호() {
        CongestionPredParser.Result r = parse(List.of(
                ok("1호선", "150", "151"),
                ok("1호선", "999999", "151")));

        assertEquals(1, r.rows().size());
        assertEquals(1, r.stats().unknownStations());
        assertTrue(r.stats().skipped() >= 1);
    }

    @Test
    @DisplayName("305-P8: 모르는 노선 이름도 행을 만들지 않는다")
    void p8_모르는_노선() {
        CongestionPredParser.Result r = parse(List.of(ok("우주선", "150", "151")));

        assertTrue(r.rows().isEmpty());
        assertEquals(1, r.stats().unknownLines());
    }

    @Test
    @DisplayName("305-P9: 날짜·슬롯이 숫자가 아니면 버린다")
    void p9_형식_오류() {
        CongestionPredParser.Result r = parse(List.of(
                row("1호선", "150", "151", "하선", "없음", "1.0", "ok", "model", "v"),
                row("1호선", "150", "151", "하선", "0", "1.0", "ok", "model", "v")
                        .entrySet().stream()
                        .collect(LinkedHashMap::new,
                                (m, e) -> m.put(e.getKey(), "pred_date".equals(e.getKey()) ? "어제" : e.getValue()),
                                LinkedHashMap::putAll)));

        assertTrue(r.rows().isEmpty());
        assertEquals(2, r.stats().skipped());
    }

    @Test
    @DisplayName("305-P10: 필수 열이 없으면 첫 행에서 멈춘다 — 조용히 빈 값으로 읽지 않는다")
    void p10_스키마_변경() {
        Map<String, String> missing = new LinkedHashMap<>(ok("1호선", "150", "151"));
        missing.remove("predictor_version");

        IllegalStateException e = assertThrows(IllegalStateException.class,
                () -> parse(List.of(missing)));
        assertTrue(e.getMessage().contains("predictor_version"), e.getMessage());
    }

    @Test
    @DisplayName("305-P11: direction 은 CSV 값을 그대로 둔다 — 재해석하지 않는다")
    void p11_방향_그대로() {
        // 2호선 지선은 내선/외선이 아니라 상선/하선으로 온다(AI 통지 07). 바꾸지 않는다.
        CongestionPredParser.Result r = parse(List.of(
                row("2호선", "250", "156", "상선", "17", "10.0", "ok", "model", "v"),
                row("2호선", "226", "227", "외선", "17", "10.0", "ok", "model", "v")));

        assertEquals("상선", r.rows().get(0).direction());
        assertEquals("외선", r.rows().get(1).direction());
    }

    @Test
    @DisplayName("305-P12: 통계가 날짜·슬롯 종류·pred_source 분포를 센다")
    void p12_통계() {
        var parser = new CongestionPredParser(codes());
        sample().forEach(parser::accept);
        CongestionPredParser.Stats st = parser.finish().stats();

        assertEquals(List.of(java.time.LocalDate.of(2026, 9, 20)), List.copyOf(st.predDates()));
        assertEquals(3, st.predSources().size(), () -> "pred_source: " + st.predSources());
        assertTrue(st.predSources().containsKey("lookup_line9"), "9호선 기준선 행이 있다");
        assertTrue(st.timeSlots() > 0 && st.timeSlots() <= 48);
    }
}
