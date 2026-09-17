package com.ssafy.s15p21a104.load;

import com.ssafy.s15p21a104.load.bike.BikeStationRow;
import com.ssafy.s15p21a104.load.bikepred.BikeStockPredRow;
import com.ssafy.s15p21a104.load.bus.BusRouteRow;
import com.ssafy.s15p21a104.load.bus.BusStopRow;
import com.ssafy.s15p21a104.load.crowd.CongestionRow;
import com.ssafy.s15p21a104.load.railgeometry.RailLinkGeometryRow;
import com.ssafy.s15p21a104.load.railgeometry.RailNodeRow;
import com.ssafy.s15p21a104.load.subway.EdgeTimeRow;
import com.ssafy.s15p21a104.load.subway.LineRow;
import com.ssafy.s15p21a104.load.subway.StationRow;
import com.ssafy.s15p21a104.load.subway.TransferMetaRow;
import java.sql.Types;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Flyway V1 테이블(지하철 4종 + 버스·따릉이 마스터 3종)에 대한 upsert. 자연키 충돌 시 값을 덮어쓰고 updated_at 을 적재 시각으로 기록한다.
 * JPA 엔티티는 조회 전용이므로 쓰지 않는다 (BE/docs/db/schema.md "적재 프로세스가 값을 기록한다").
 * edge_time 은 행이 많아(엣지 × 144) ROW·BATCH 두 모드를 두고 처리량을 비교한다 — BE/docs/perf 참고.
 */
public class UpsertWriter {

    public enum WriteMode { ROW, BATCH }

    static final int BATCH_SIZE = 1000;

    private static final String UPSERT_LINE = """
            INSERT INTO line (line_id, name, updated_at) VALUES (?, ?, now())
            ON CONFLICT (line_id) DO UPDATE SET name = EXCLUDED.name, updated_at = now()
            """;

    private static final String UPSERT_STATION = """
            INSERT INTO station (station_id, name, lat, lng, updated_at) VALUES (?, ?, ?, ?, now())
            ON CONFLICT (station_id) DO UPDATE
              SET name = EXCLUDED.name, lat = EXCLUDED.lat, lng = EXCLUDED.lng, updated_at = now()
            """;

    private static final String UPSERT_TRANSFER = """
            INSERT INTO transfer_meta (station_id, from_line, to_line, walk_sec, source) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (station_id, from_line, to_line) DO UPDATE
              SET walk_sec = EXCLUDED.walk_sec, source = EXCLUDED.source
            """;

    private static final String UPSERT_EDGE_TIME = """
            INSERT INTO edge_time (from_node, to_node, mode, route_id, dow_type, time_slot, travel_sec, wait_sec, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (from_node, to_node, mode, route_id, dow_type, time_slot) DO UPDATE
              SET travel_sec = EXCLUDED.travel_sec, wait_sec = EXCLUDED.wait_sec, source = EXCLUDED.source, updated_at = now()
            """;

    private static final String UPSERT_BUS_STOP = """
            INSERT INTO bus_stop (stop_id, name, lat, lng, updated_at) VALUES (?, ?, ?, ?, now())
            ON CONFLICT (stop_id) DO UPDATE
              SET name = EXCLUDED.name, lat = EXCLUDED.lat, lng = EXCLUDED.lng, updated_at = now()
            """;

    private static final String UPSERT_BUS_ROUTE = """
            INSERT INTO bus_route (route_id, name, updated_at) VALUES (?, ?, now())
            ON CONFLICT (route_id) DO UPDATE SET name = EXCLUDED.name, updated_at = now()
            """;

    private static final String UPSERT_BIKE_STATION = """
            INSERT INTO bike_station (rental_id, name, lat, lng, dock_count, updated_at) VALUES (?, ?, ?, ?, ?, now())
            ON CONFLICT (rental_id) DO UPDATE
              SET name = EXCLUDED.name, lat = EXCLUDED.lat, lng = EXCLUDED.lng, dock_count = EXCLUDED.dock_count, updated_at = now()
            """;

    private static final String UPSERT_RAIL_NODE = """
            INSERT INTO rail_node (node_id, lat, lng, station_name_raw, updated_at) VALUES (?, ?, ?, ?, now())
            ON CONFLICT (node_id) DO UPDATE
              SET lat = EXCLUDED.lat, lng = EXCLUDED.lng, station_name_raw = EXCLUDED.station_name_raw, updated_at = now()
            """;

    private static final String UPSERT_RAIL_LINK_GEOMETRY = """
            INSERT INTO rail_link_geometry
              (link_id, from_node_id, to_node_id, line_name_raw, physical_line_name_raw, line_id, length_km, geometry, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, now())
            ON CONFLICT (link_id) DO UPDATE
              SET from_node_id = EXCLUDED.from_node_id, to_node_id = EXCLUDED.to_node_id,
                  line_name_raw = EXCLUDED.line_name_raw, physical_line_name_raw = EXCLUDED.physical_line_name_raw,
                  line_id = EXCLUDED.line_id, length_km = EXCLUDED.length_km, geometry = EXCLUDED.geometry, updated_at = now()
            """;

    private static final String UPSERT_CONGESTION = """
            INSERT INTO congestion (target_type, target_id, dow_type, time_slot, level, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (target_type, target_id, dow_type, time_slot) DO UPDATE
            SET level = EXCLUDED.level, source = EXCLUDED.source, updated_at = now()
            """;

    private static final String UPSERT_BIKE_STOCK_PRED = """
            INSERT INTO bike_stock_pred
              (rental_id, dow_type, time_slot, exp_bikes, p_empty, p_full, source, prediction_source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (rental_id, dow_type, time_slot) DO UPDATE
              SET exp_bikes = EXCLUDED.exp_bikes, p_empty = EXCLUDED.p_empty, p_full = EXCLUDED.p_full,
                  source = EXCLUDED.source, prediction_source = EXCLUDED.prediction_source, updated_at = now()
            """;

    private final JdbcTemplate jdbc;

    public UpsertWriter(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public int upsertCongestion(List<CongestionRow> rows) {
        jdbc.batchUpdate(UPSERT_CONGESTION, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.targetType());
            ps.setString(2, r.targetId());
            ps.setInt(3, r.dowType());
            ps.setInt(4, r.timeSlot());
            ps.setBigDecimal(5, r.level());
            ps.setString(6, r.source());
        });
        return rows.size();
    }

    /**
     * 재고 예측. 대여소 약 2,800 × 요일 3 × 슬롯 48 = 40만 행이라 배치로 쓴다.
     * {@code prediction_source} 는 null 이 올 수 있어 {@code setObject} 로 넣는다 — 그 열이 없던 시절의 산출물이다.
     */
    public int upsertBikeStockPred(List<BikeStockPredRow> rows) {
        jdbc.batchUpdate(UPSERT_BIKE_STOCK_PRED, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.rentalId());
            ps.setInt(2, r.dowType());
            ps.setInt(3, r.timeSlot());
            ps.setBigDecimal(4, r.expBikes());
            ps.setBigDecimal(5, r.pEmpty());
            ps.setBigDecimal(6, r.pFull());
            ps.setString(7, r.source());
            ps.setObject(8, r.predictionSource(), Types.VARCHAR);
        });
        return rows.size();
    }

    /** 적재된 대여소 ID. 재고 예측 적재가 마스터 대조(없는 대여소는 경고)에 쓴다. */
    public Set<String> existingRentalIds() {
        return Set.copyOf(jdbc.queryForList("SELECT rental_id FROM bike_station", String.class));
    }

    /** 적재된 역 ID. 혼잡도처럼 다른 테이블을 참조하는 적재가 대상 존재를 검증하는 데 쓴다. */
    public Set<String> existingStationIds() {
        return Set.copyOf(jdbc.queryForList("SELECT station_id FROM station", String.class));
    }

    /** 적재된 노선 ID. */
    public Set<String> existingLineIds() {
        return Set.copyOf(jdbc.queryForList("SELECT line_id FROM line", String.class));
    }

    public int upsertBusStops(List<BusStopRow> rows) {
        jdbc.batchUpdate(UPSERT_BUS_STOP, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.stopId());
            ps.setString(2, r.name());
            ps.setObject(3, r.lat(), Types.DOUBLE);
            ps.setObject(4, r.lng(), Types.DOUBLE);
        });
        return rows.size();
    }

    public int upsertBusRoutes(List<BusRouteRow> rows) {
        jdbc.batchUpdate(UPSERT_BUS_ROUTE, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.routeId());
            ps.setString(2, r.name());
        });
        return rows.size();
    }

    public int upsertBikeStations(List<BikeStationRow> rows) {
        jdbc.batchUpdate(UPSERT_BIKE_STATION, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.rentalId());
            ps.setString(2, r.name());
            ps.setObject(3, r.lat(), Types.DOUBLE);
            ps.setObject(4, r.lng(), Types.DOUBLE);
            ps.setObject(5, r.dockCount(), Types.INTEGER);
        });
        return rows.size();
    }

    public int upsertLines(List<LineRow> rows) {
        jdbc.batchUpdate(UPSERT_LINE, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.lineId());
            ps.setString(2, r.name());
        });
        return rows.size();
    }

    public int upsertStations(List<StationRow> rows) {
        jdbc.batchUpdate(UPSERT_STATION, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.stationId());
            ps.setString(2, r.name());
            ps.setObject(3, r.lat(), Types.DOUBLE);
            ps.setObject(4, r.lng(), Types.DOUBLE);
        });
        return rows.size();
    }

    public int upsertTransfers(List<TransferMetaRow> rows) {
        jdbc.batchUpdate(UPSERT_TRANSFER, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.stationId());
            ps.setString(2, r.fromLine());
            ps.setString(3, r.toLine());
            ps.setInt(4, r.walkSec());
            ps.setString(5, r.source());
        });
        return rows.size();
    }

    /**
     * prune 결과. dry-run 이면 deletedEdgeRows·deletedStationIds 는 비어 있고 staleEdges 만 의미가 있다.
     *
     * @param staleEdges          덮는 노선에서 이번 실행에 없는 (from, to, route) 수
     * @param deletedEdgeRows     실제 지운 edge_time 행 수
     * @param deletedTransferRows 실제 지운 transfer_meta 행 수 (덮는 노선의 환승 중 이번 실행에 없는 역의 것)
     * @param deletedStationIds   실제 지운 고아 역 (엣지·환승 어디에도 안 쓰이고 이번 실행에도 없는 역)
     */
    public record PruneResult(int staleEdges, int deletedEdgeRows, int deletedTransferRows, List<String> staleEdgeKeys,
                              List<String> deletedStationIds) {
    }

    /**
     * 시각표가 정본이 된 뒤 남는 옛 행을 지운다. upsert 만으로는 사라진 구간(6호선 응암순환 역방향, 개명 전 역)이 남기 때문이다.
     * 엣지는 coveredLines 의 SUBWAY 행 중 keptEdgeKeys("from|to|route")에 없는 것만, 환승은 coveredLines 에 걸린 행 중 station_id 가
     * keptStationIds 에 없는 것만(개명 전 ID 등), 역은 어느 edge_time·transfer_meta 에도 참조되지 않고 keptStationIds 에도 없는 것만 지운다.
     * dry-run 은 세기만 한다 (엣지 삭제 뒤 고아가 될 역은 세지 못한다).
     */
    public PruneResult pruneSubway(Set<String> coveredLines, Set<String> keptEdgeKeys, Set<String> keptStationIds, boolean dryRun) {
        List<String[]> stale = new ArrayList<>();
        if (!coveredLines.isEmpty()) {
            String placeholders = String.join(",", Collections.nCopies(coveredLines.size(), "?"));
            List<String[]> existing = jdbc.query(
                    "SELECT DISTINCT from_node, to_node, route_id FROM edge_time WHERE mode = 'SUBWAY' AND route_id IN (" + placeholders + ")",
                    (rs, i) -> new String[] {rs.getString(1), rs.getString(2), rs.getString(3)},
                    coveredLines.toArray());
            for (String[] e : existing) {
                if (!keptEdgeKeys.contains(e[0] + "|" + e[1] + "|" + e[2])) {
                    stale.add(e);
                }
            }
        }
        List<String> staleKeys = stale.stream().map(e -> e[0] + "|" + e[1] + "|" + e[2]).sorted().toList();
        if (dryRun) {
            return new PruneResult(stale.size(), 0, 0, staleKeys, List.of());
        }
        int deletedRows = 0;
        for (String[] e : stale) {
            deletedRows += jdbc.update("DELETE FROM edge_time WHERE mode = 'SUBWAY' AND from_node = ? AND to_node = ? AND route_id = ?",
                    e[0], e[1], e[2]);
        }
        int deletedTransfers = 0;
        if (!coveredLines.isEmpty() && !keptStationIds.isEmpty()) {
            String linePh = String.join(",", Collections.nCopies(coveredLines.size(), "?"));
            String stationPh = String.join(",", Collections.nCopies(keptStationIds.size(), "?"));
            List<Object> args = new ArrayList<>(coveredLines);
            args.addAll(coveredLines);
            args.addAll(keptStationIds);
            deletedTransfers = jdbc.update("DELETE FROM transfer_meta WHERE (from_line IN (" + linePh + ") OR to_line IN (" + linePh
                    + ")) AND station_id NOT IN (" + stationPh + ")", args.toArray());
        }
        List<String> orphans = jdbc.queryForList("""
                SELECT s.station_id FROM station s
                WHERE NOT EXISTS (SELECT 1 FROM edge_time e WHERE e.from_node = s.station_id OR e.to_node = s.station_id)
                  AND NOT EXISTS (SELECT 1 FROM transfer_meta t WHERE t.station_id = s.station_id)
                ORDER BY s.station_id
                """, String.class).stream().filter(id -> !keptStationIds.contains(id)).toList();
        for (String id : orphans) {
            jdbc.update("DELETE FROM station WHERE station_id = ?", id);
        }
        return new PruneResult(stale.size(), deletedRows, deletedTransfers, staleKeys, orphans);
    }

    public int upsertRailNodes(List<RailNodeRow> rows) {
        jdbc.batchUpdate(UPSERT_RAIL_NODE, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.nodeId());
            ps.setDouble(2, r.lat());
            ps.setDouble(3, r.lng());
            ps.setString(4, r.stationNameRaw());
        });
        return rows.size();
    }

    public int upsertRailLinkGeometry(List<RailLinkGeometryRow> rows) {
        jdbc.batchUpdate(UPSERT_RAIL_LINK_GEOMETRY, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.linkId());
            ps.setString(2, r.fromNodeId());
            ps.setString(3, r.toNodeId());
            ps.setString(4, r.lineNameRaw());
            ps.setString(5, r.physicalLineNameRaw());
            ps.setString(6, r.lineId());
            ps.setObject(7, r.lengthKm(), Types.DOUBLE);
            ps.setString(8, r.geometryGeojson());
        });
        return rows.size();
    }

    public int upsertEdgeTimes(List<EdgeTimeRow> rows, WriteMode mode) {
        if (mode == WriteMode.ROW) {
            for (EdgeTimeRow r : rows) {
                jdbc.update(UPSERT_EDGE_TIME, r.fromNode(), r.toNode(), r.mode(), r.routeId(),
                        r.dowType(), r.timeSlot(), r.travelSec(), r.waitSec(), r.source());
            }
            return rows.size();
        }
        jdbc.batchUpdate(UPSERT_EDGE_TIME, rows, BATCH_SIZE, (ps, r) -> {
            ps.setString(1, r.fromNode());
            ps.setString(2, r.toNode());
            ps.setString(3, r.mode());
            ps.setString(4, r.routeId());
            ps.setInt(5, r.dowType());
            ps.setInt(6, r.timeSlot());
            ps.setInt(7, r.travelSec());
            ps.setInt(8, r.waitSec());
            ps.setString(9, r.source());
        });
        return rows.size();
    }
}
