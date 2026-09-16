package com.ssafy.s15p21a104.load.bus;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * "버스노선별 정류소 정보"(OA-1095, 노선 × 경유 정류소) → bus_route 행. ROUTE_ID 별 첫 행의 노선명을 쓴다.
 * 경유 순번은 V1 스키마에 테이블이 없어 적재하지 않는다 — 후속 BUS 엣지 작업에서 같은 파일을 다시 읽는다.
 */
public final class BusRouteParser {

    private final List<String> warnings = new ArrayList<>();

    public List<BusRouteRow> parse(List<Map<String, String>> routeStopRows) {
        Map<String, BusRouteRow> out = new LinkedHashMap<>();
        Set<String> conflicted = new HashSet<>();
        for (Map<String, String> row : routeStopRows) {
            String id = value(row, "ROUTE_ID");
            String name = value(row, "노선명");
            if (id.isEmpty()) {
                warnings.add("ROUTE_ID 없는 행: 노선명 '" + name + "', NODE_ID " + value(row, "NODE_ID"));
                continue;
            }
            if (name.isEmpty()) {
                warnings.add("노선명 없는 행: ROUTE_ID " + id);
                continue;
            }
            BusRouteRow existing = out.get(id);
            if (existing == null) {
                out.put(id, new BusRouteRow(id, name));
            } else if (!existing.name().equals(name) && conflicted.add(id)) {
                warnings.add("같은 ROUTE_ID 에 다른 노선명: " + id + " '" + existing.name() + "' vs '" + name + "' — 첫 값을 쓴다");
            }
        }
        return List.copyOf(out.values());
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }
}
