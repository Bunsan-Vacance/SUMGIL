package com.ssafy.s15p21a104.load;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import com.ssafy.s15p21a104.load.subway.EdgeRow;
import com.ssafy.s15p21a104.load.subway.EdgeTimeExpander;
import com.ssafy.s15p21a104.load.subway.EdgeTimeRow;
import com.ssafy.s15p21a104.load.subway.LineRow;
import com.ssafy.s15p21a104.load.subway.StationRow;
import com.ssafy.s15p21a104.load.subway.TransferMetaRow;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * 실제 PostgreSQL(Flyway V1 스키마)에 대한 upsert 통합 테스트.
 * 두 번 실행해도 건수가 같아야 하고(멱등), 같은 키의 값은 나중 값으로 덮어써야 한다(avg → timetable).
 * 테스트 데이터는 'IT_' 접두어로 격리하고 끝나면 지운다.
 */
@SpringBootTest
class UpsertWriterIT {

    @Autowired
    JdbcTemplate jdbc;

    UpsertWriter writer;

    private static final String L = "IT_L1";
    private static final String A = "IT_A";
    private static final String B = "IT_B";

    @BeforeEach
    void setUp() {
        writer = new UpsertWriter(jdbc);
        cleanUp();
    }

    @AfterEach
    void cleanUp() {
        jdbc.update("DELETE FROM edge_time WHERE route_id = ?", L);
        jdbc.update("DELETE FROM transfer_meta WHERE station_id IN (?, ?)", A, B);
        jdbc.update("DELETE FROM station WHERE station_id IN (?, ?)", A, B);
        jdbc.update("DELETE FROM line WHERE line_id = ?", L);
    }

    @Test
    @DisplayName("line·station·transfer_meta 를 넣고 다시 넣어도 건수가 같다")
    void mastersAreIdempotent() {
        List<LineRow> lines = List.of(new LineRow(L, "IT 노선"));
        List<StationRow> stations = List.of(
                new StationRow(A, "가", 37.5, 127.0, Set.of(L)),
                new StationRow(B, "나", null, null, Set.of(L)));
        List<TransferMetaRow> transfers = List.of(new TransferMetaRow(A, L, "IT_L2", 90, "extract"));

        writer.upsertLines(lines);
        writer.upsertStations(stations);
        writer.upsertTransfers(transfers);
        writer.upsertLines(lines);
        writer.upsertStations(stations);
        writer.upsertTransfers(transfers);

        assertEquals(1, count("line", "line_id = ?", L));
        assertEquals(2, count("station", "station_id IN (?, ?)", A, B));
        assertEquals(1, count("transfer_meta", "station_id = ?", A));
        assertNotNull(jdbc.queryForObject("SELECT updated_at FROM station WHERE station_id = ?", Object.class, A));
        assertEquals(null, jdbc.queryForObject("SELECT lat FROM station WHERE station_id = ?", Double.class, B));
    }

    @Test
    @DisplayName("edge_time 144행 × 2 엣지를 행 단위와 배치 두 방식으로 넣어도 결과가 같고 멱등하다")
    void edgeTimesRowAndBatchAreEquivalentAndIdempotent() {
        writer.upsertLines(List.of(new LineRow(L, "IT 노선")));
        writer.upsertStations(List.of(
                new StationRow(A, "가", null, null, Set.of(L)),
                new StationRow(B, "나", null, null, Set.of(L))));
        List<EdgeTimeRow> rows = EdgeTimeExpander.expandAll(List.of(
                new EdgeRow(A, B, "SUBWAY", L, 100, "avg"),
                new EdgeRow(B, A, "SUBWAY", L, 100, "avg")));

        int written = writer.upsertEdgeTimes(rows, UpsertWriter.WriteMode.ROW);
        assertEquals(288, written);
        assertEquals(288, count("edge_time", "route_id = ?", L));

        writer.upsertEdgeTimes(rows, UpsertWriter.WriteMode.BATCH);
        assertEquals(288, count("edge_time", "route_id = ?", L));
    }

    @Test
    @DisplayName("같은 키에 새 값이 오면 덮어쓴다 — avg 120초가 timetable 90초로")
    void overwritesExistingKey() {
        writer.upsertLines(List.of(new LineRow(L, "IT 노선")));
        writer.upsertStations(List.of(
                new StationRow(A, "가", null, null, Set.of(L)),
                new StationRow(B, "나", null, null, Set.of(L))));
        writer.upsertEdgeTimes(EdgeTimeExpander.expand(new EdgeRow(A, B, "SUBWAY", L, 120, "avg")),
                UpsertWriter.WriteMode.BATCH);
        writer.upsertEdgeTimes(EdgeTimeExpander.expand(new EdgeRow(A, B, "SUBWAY", L, 90, "timetable")),
                UpsertWriter.WriteMode.BATCH);

        assertEquals(144, count("edge_time", "route_id = ?", L));
        assertEquals(90, jdbc.queryForObject(
                "SELECT travel_sec FROM edge_time WHERE route_id = ? AND dow_type = 0 AND time_slot = 0", Integer.class, L));
        assertEquals("timetable", jdbc.queryForObject(
                "SELECT source FROM edge_time WHERE route_id = ? AND dow_type = 0 AND time_slot = 0", String.class, L));
    }

    private int count(String table, String where, Object... args) {
        Integer n = jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE " + where, Integer.class, args);
        return n == null ? 0 : n;
    }
}
