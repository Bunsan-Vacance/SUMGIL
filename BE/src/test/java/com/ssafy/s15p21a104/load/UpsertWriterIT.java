package com.ssafy.s15p21a104.load;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import com.ssafy.s15p21a104.load.bike.BikeStationRow;
import com.ssafy.s15p21a104.load.bus.BusRouteRow;
import com.ssafy.s15p21a104.load.bus.BusStopRow;
import com.ssafy.s15p21a104.load.crowd.CongestionRow;
import com.ssafy.s15p21a104.load.subway.EdgeRow;
import java.math.BigDecimal;
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
    private static final String C = "IT_C";
    private static final String D = "IT_D";
    private static final String E = "IT_E";
    private static final String STOP = "IT_STOP";
    private static final String ROUTE = "IT_ROUTE";
    private static final String RENT = "IT_ST-1";

    @BeforeEach
    void setUp() {
        writer = new UpsertWriter(jdbc);
        cleanUp();
    }

    @AfterEach
    void cleanUp() {
        jdbc.update("DELETE FROM bus_stop WHERE stop_id IN (?, ?)", STOP, STOP + "2");
        jdbc.update("DELETE FROM bus_route WHERE route_id = ?", ROUTE);
        jdbc.update("DELETE FROM bike_station WHERE rental_id IN (?, ?)", RENT, RENT + "2");
        jdbc.update("DELETE FROM edge_time WHERE route_id = ?", L);
        jdbc.update("DELETE FROM transfer_meta WHERE station_id IN (?, ?, ?, ?, ?)", A, B, C, D, E);
        jdbc.update("DELETE FROM congestion WHERE target_id IN (?, ?)", A, L);
        jdbc.update("DELETE FROM station WHERE station_id IN (?, ?, ?, ?, ?)", A, B, C, D, E);
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

    @Test
    @DisplayName("prune: 덮는 노선에서 이번 실행에 없는 엣지 행, 이번 실행에 없는 역의 환승 행, 고아 역을 지우고 — 이번 실행에 있는 역의 환승은 남긴다")
    void pruneRemovesStaleEdgesTransfersAndOrphanStations() {
        writer.upsertLines(List.of(new LineRow(L, "IT 노선")));
        writer.upsertStations(List.of(
                new StationRow(A, "가", null, null, Set.of(L)),
                new StationRow(B, "나", null, null, Set.of(L)),
                new StationRow(C, "고아", null, null, Set.of(L)),
                new StationRow(D, "환승만", null, null, Set.of(L)),
                new StationRow(E, "옛이름", null, null, Set.of(L))));
        // D 는 이번 실행에도 있는 역(kept) → 환승 유지. E 는 개명 전 ID 처럼 이번 실행에 없는 역 → 환승·역 모두 삭제
        writer.upsertTransfers(List.of(
                new TransferMetaRow(D, L, "IT_L2", 90, "extract"),
                new TransferMetaRow(E, L, "IT_L2", 90, "extract")));
        writer.upsertEdgeTimes(EdgeTimeExpander.expandAll(List.of(
                new EdgeRow(A, B, "SUBWAY", L, 100, "timetable"),
                new EdgeRow(B, A, "SUBWAY", L, 100, "timetable"))), UpsertWriter.WriteMode.BATCH);

        UpsertWriter.PruneResult result = writer.pruneSubway(Set.of(L), Set.of(A + "|" + B + "|" + L), Set.of(A, B, D), false);

        assertEquals(1, result.staleEdges());
        assertEquals(144, result.deletedEdgeRows());
        assertEquals(1, result.deletedTransferRows());
        assertEquals(List.of(C, E), result.deletedStationIds());
        assertEquals(144, count("edge_time", "route_id = ?", L));
        assertEquals(0, count("edge_time", "route_id = ? AND from_node = ?", L, B));
        assertEquals(0, count("station", "station_id IN (?, ?)", C, E));
        assertEquals(0, count("transfer_meta", "station_id = ?", E));
        assertEquals(1, count("station", "station_id = ?", D));
        assertEquals(1, count("transfer_meta", "station_id = ?", D));
    }

    @Test
    @DisplayName("prune dry-run 은 지울 것을 세기만 하고 아무것도 지우지 않는다")
    void pruneDryRunDeletesNothing() {
        writer.upsertLines(List.of(new LineRow(L, "IT 노선")));
        writer.upsertStations(List.of(new StationRow(A, "가", null, null, Set.of(L)), new StationRow(B, "나", null, null, Set.of(L))));
        writer.upsertEdgeTimes(EdgeTimeExpander.expandAll(List.of(new EdgeRow(A, B, "SUBWAY", L, 100, "timetable"))),
                UpsertWriter.WriteMode.BATCH);

        UpsertWriter.PruneResult result = writer.pruneSubway(Set.of(L), Set.of(), Set.of(), true);

        assertEquals(1, result.staleEdges());
        assertEquals(144, count("edge_time", "route_id = ?", L));
        assertEquals(2, count("station", "station_id IN (?, ?)", A, B));
    }

    @Test
    @DisplayName("bus_stop·bus_route·bike_station 을 넣고 다시 넣어도 건수가 같다 — 좌표·거치대수 null 도 그대로")
    void busAndBikeMastersAreIdempotent() {
        List<BusStopRow> stops = List.of(
                new BusStopRow(STOP, "IT 정류소", 37.5, 127.0),
                new BusStopRow(STOP + "2", "IT 좌표없음", null, null));
        List<BusRouteRow> routes = List.of(new BusRouteRow(ROUTE, "IT 147"));
        List<BikeStationRow> bikes = List.of(
                new BikeStationRow(RENT, "IT 대여소", 37.5, 127.0, 15),
                new BikeStationRow(RENT + "2", "IT 거치대없음", 37.5, 127.0, null));

        assertEquals(2, writer.upsertBusStops(stops));
        assertEquals(1, writer.upsertBusRoutes(routes));
        assertEquals(2, writer.upsertBikeStations(bikes));
        writer.upsertBusStops(stops);
        writer.upsertBusRoutes(routes);
        writer.upsertBikeStations(bikes);

        assertEquals(2, count("bus_stop", "stop_id IN (?, ?)", STOP, STOP + "2"));
        assertEquals(1, count("bus_route", "route_id = ?", ROUTE));
        assertEquals(2, count("bike_station", "rental_id IN (?, ?)", RENT, RENT + "2"));
        assertEquals(null, jdbc.queryForObject("SELECT lat FROM bus_stop WHERE stop_id = ?", Double.class, STOP + "2"));
        assertEquals(null, jdbc.queryForObject("SELECT dock_count FROM bike_station WHERE rental_id = ?", Integer.class, RENT + "2"));
        assertNotNull(jdbc.queryForObject("SELECT updated_at FROM bus_stop WHERE stop_id = ?", Object.class, STOP));
    }

    @Test
    @DisplayName("마스터 3종은 같은 키에 새 값이 오면 이름·좌표·거치대수를 덮어쓴다")
    void mastersOverwriteExistingKey() {
        writer.upsertBusStops(List.of(new BusStopRow(STOP, "옛 이름", 37.5, 127.0)));
        writer.upsertBusRoutes(List.of(new BusRouteRow(ROUTE, "옛 147")));
        writer.upsertBikeStations(List.of(new BikeStationRow(RENT, "옛 대여소", 37.5, 127.0, 10)));

        writer.upsertBusStops(List.of(new BusStopRow(STOP, "새 이름", 37.6, 127.1)));
        writer.upsertBusRoutes(List.of(new BusRouteRow(ROUTE, "새 147")));
        writer.upsertBikeStations(List.of(new BikeStationRow(RENT, "새 대여소", 37.6, 127.1, 20)));

        assertEquals("새 이름", jdbc.queryForObject("SELECT name FROM bus_stop WHERE stop_id = ?", String.class, STOP));
        assertEquals(37.6, jdbc.queryForObject("SELECT lat FROM bus_stop WHERE stop_id = ?", Double.class, STOP), 1e-9);
        assertEquals("새 147", jdbc.queryForObject("SELECT name FROM bus_route WHERE route_id = ?", String.class, ROUTE));
        assertEquals(20, jdbc.queryForObject("SELECT dock_count FROM bike_station WHERE rental_id = ?", Integer.class, RENT));
    }

    @Test
    @DisplayName("congestion 을 넣고 다시 넣어도 건수가 같고, 같은 키의 값은 새 값으로 덮어쓴다 — 100 초과 값도 그대로 들어간다")
    void congestionUpsertIsIdempotent() {
        List<CongestionRow> rows = List.of(
                new CongestionRow("STATION", A, 0, 17, new BigDecimal("92.2"), "stat"),
                new CongestionRow("STATION", A, 0, 18, new BigDecimal("144.6"), "stat"),
                new CongestionRow("LINE", L, 0, 17, new BigDecimal("66.1"), "stat"));

        assertEquals(3, writer.upsertCongestion(rows));
        assertEquals(3, writer.upsertCongestion(rows));
        assertEquals(3, count("congestion", "target_id IN (?, ?)", A, L));
        assertEquals(new BigDecimal("144.6"),
                jdbc.queryForObject("SELECT level FROM congestion WHERE target_id = ? AND time_slot = 18", BigDecimal.class, A));

        writer.upsertCongestion(List.of(new CongestionRow("STATION", A, 0, 17, new BigDecimal("11.1"), "live")));

        assertEquals(new BigDecimal("11.1"),
                jdbc.queryForObject("SELECT level FROM congestion WHERE target_id = ? AND time_slot = 17", BigDecimal.class, A));
        assertEquals("live",
                jdbc.queryForObject("SELECT source FROM congestion WHERE target_id = ? AND time_slot = 17", String.class, A));
        assertEquals(3, count("congestion", "target_id IN (?, ?)", A, L));
    }

    private int count(String table, String where, Object... args) {
        Integer n = jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE " + where, Integer.class, args);
        return n == null ? 0 : n;
    }
}
