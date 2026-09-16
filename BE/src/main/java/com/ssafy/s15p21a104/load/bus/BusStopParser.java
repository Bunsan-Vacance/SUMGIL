package com.ssafy.s15p21a104.load.bus;

import com.ssafy.s15p21a104.load.Coords;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 열린데이터광장 "서울시 버스정류소 위치정보"(OA-15067) → bus_stop 행.
 * 위치정보 파일이 정본이고, "버스노선별 정류소 정보"(OA-1095)에만 있는 정류소(서울 밖 경기 구간)는 그 파일의 좌표로 보충한다 —
 * 노선의 경유 정류소가 끊기지 않게 하기 위해서다. 둘 다 있으면 위치정보 파일 값을 쓴다.
 */
public final class BusStopParser {

    private final List<String> warnings = new ArrayList<>();
    private int addedFromRouteFile;

    /**
     * @param stopRows      위치정보 파일 행 (NODE_ID · ARS_ID · 정류소명 · X좌표 · Y좌표 · 정류소타입)
     * @param routeStopRows 노선별 정류소 파일 행 (ROUTE_ID · 노선명 · 순번 · NODE_ID · ARS_ID · 정류소명 · X좌표 · Y좌표). 비어 있어도 된다
     */
    public List<BusStopRow> parse(List<Map<String, String>> stopRows, List<Map<String, String>> routeStopRows) {
        Map<String, BusStopRow> out = new LinkedHashMap<>();
        for (Map<String, String> row : stopRows) {
            BusStopRow stop = toRow(row, "위치정보");
            if (stop == null) {
                continue;
            }
            if (out.putIfAbsent(stop.stopId(), stop) != null) {
                warnings.add("위치정보 파일에 NODE_ID 중복: " + stop.stopId() + " — 첫 행을 쓴다");
            }
        }
        addedFromRouteFile = 0;
        for (Map<String, String> row : routeStopRows) {
            String id = value(row, "NODE_ID");
            if (id.isEmpty() || out.containsKey(id)) {
                continue;
            }
            BusStopRow stop = toRow(row, "노선별");
            if (stop == null) {
                continue;
            }
            out.put(id, stop);
            addedFromRouteFile++;
        }
        return List.copyOf(out.values());
    }

    private BusStopRow toRow(Map<String, String> row, String source) {
        String id = value(row, "NODE_ID");
        String name = value(row, "정류소명");
        if (id.isEmpty()) {
            warnings.add(source + " 파일에 NODE_ID 없는 행: 정류소명 '" + name + "'");
            return null;
        }
        if (name.isEmpty()) {
            warnings.add(source + " 파일에 정류소명 없는 행: NODE_ID " + id);
            return null;
        }
        // X좌표 = 경도, Y좌표 = 위도 (WGS84, 도 단위). 2026-09-02 배포분 실측: 경도 126.80~127.18, 위도 37.43~37.69
        Double lng = Coords.parseOrNull(row.get("X좌표"));
        Double lat = Coords.parseOrNull(row.get("Y좌표"));
        if (lat == null || lng == null) {
            warnings.add("좌표 없음: " + id + " " + name + " (" + source + ")");
        }
        return new BusStopRow(id, name, lat, lng);
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    /** 노선별 파일에서만 발견되어 보충한 정류소 수 (로그·문서용). */
    public int addedFromRouteFile() {
        return addedFromRouteFile;
    }
}
