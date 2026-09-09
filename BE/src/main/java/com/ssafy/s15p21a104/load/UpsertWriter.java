package com.ssafy.s15p21a104.load;

import com.ssafy.s15p21a104.load.bike.BikeStationRow;
import com.ssafy.s15p21a104.load.bus.BusRouteRow;
import com.ssafy.s15p21a104.load.bus.BusStopRow;
import com.ssafy.s15p21a104.load.railgeometry.RailLinkGeometryRow;
import com.ssafy.s15p21a104.load.railgeometry.RailNodeRow;
import com.ssafy.s15p21a104.load.subway.EdgeTimeRow;
import com.ssafy.s15p21a104.load.subway.LineRow;
import com.ssafy.s15p21a104.load.subway.StationRow;
import com.ssafy.s15p21a104.load.subway.TransferMetaRow;
import java.sql.Types;
import java.util.List;
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

    private final JdbcTemplate jdbc;

    public UpsertWriter(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
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
