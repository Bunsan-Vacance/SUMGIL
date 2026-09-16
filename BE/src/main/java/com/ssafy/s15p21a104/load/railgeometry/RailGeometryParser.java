package com.ssafy.s15p21a104.load.railgeometry;

import com.ssafy.s15p21a104.load.Coords;
import com.ssafy.s15p21a104.load.subway.LineCodes;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * {@code convert_ktdb.py}가 만든 KTDB node/link CSV → 적재 행.
 * 좌표 변환·CP949 디코딩은 전처리 스크립트가 이미 끝내놨다 — 여기서는 line_id 매칭만 한다.
 */
public final class RailGeometryParser {

    private final List<String> warnings = new ArrayList<>();

    public List<RailNodeRow> parseNodes(List<Map<String, String>> rows) {
        List<RailNodeRow> out = new ArrayList<>(rows.size());
        for (Map<String, String> row : rows) {
            String id = value(row, "node_id");
            if (id.isEmpty()) {
                warnings.add("node_id 없는 행: " + row);
                continue;
            }
            Double lat = Coords.parseOrNull(row.get("lat"));
            Double lng = Coords.parseOrNull(row.get("lng"));
            if (lat == null || lng == null) {
                warnings.add("좌표 없음: node " + id);
                continue;
            }
            out.add(new RailNodeRow(id, lat, lng, value(row, "station_name_raw")));
        }
        return out;
    }

    public List<RailLinkGeometryRow> parseLinks(List<Map<String, String>> rows) {
        List<RailLinkGeometryRow> out = new ArrayList<>(rows.size());
        int matched = 0;
        for (Map<String, String> row : rows) {
            String id = value(row, "link_id");
            String from = value(row, "from_node_id");
            String to = value(row, "to_node_id");
            if (id.isEmpty() || from.isEmpty() || to.isEmpty()) {
                warnings.add("link_id/from/to 없는 행: " + row);
                continue;
            }
            String lineNameRaw = value(row, "line_name_raw");
            String lineId = LineCodes.fromKtdbServiceName(lineNameRaw).orElse(null);
            if (lineId != null) {
                matched++;
            }
            out.add(new RailLinkGeometryRow(
                    id, from, to,
                    lineNameRaw, value(row, "physical_line_name_raw"), lineId,
                    Coords.parseOrNull(row.get("length_km")),
                    row.get("geometry_geojson")
            ));
        }
        warnings.add("line_id 매칭: " + matched + " / " + out.size()
                + " (나머지는 우리 노선표 밖 — 정상)");
        return out;
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }
}
