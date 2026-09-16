package com.ssafy.s15p21a104.domain.route.bus;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder.RouteStop;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 노선별 경유 정류소 원천 CSV 리더. 기동 시 1회 읽는다.
 *
 * <p>경유 순번은 V1 스키마에 테이블이 없어 적재하지 않는다
 * ({@code load/bus/BusRouteParser} 주석). 원천 파일을 직접 읽어 순번·좌표를
 * 묶어 돌려준다. 적재 파서(`load/bus`)는 손대지 않는다.
 */
public final class BusRouteStopsReader {

    /** 원천 CSV 경로 (resources 기준). */
    static final String RESOURCE_PATH = "data/bus/seoul-bus-route-stops_20260902.csv";

    private BusRouteStopsReader() {
    }

    /**
     * 원천 CSV를 읽어 노선 ID → 경유 정류소 목록으로 묶는다.
     *
     * @return 노선별 경유 정류소. 파일이 없으면 빈 맵
     */
    public static Map<String, List<RouteStop>> read() {
        Map<String, List<RouteStop>> routes = new LinkedHashMap<>();
        try (InputStream in = resourceStream();
                BufferedReader reader = new BufferedReader(
                        new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String header = reader.readLine();
            if (header == null) {
                return Map.of();
            }
            String[] columns = header.split(",", -1);
            int routeIdx = indexOf(columns, "ROUTE_ID");
            int seqIdx = indexOf(columns, "순번");
            int nodeIdx = indexOf(columns, "NODE_ID");
            int nameIdx = indexOf(columns, "정류소명");
            int xIdx = indexOf(columns, "X좌표");
            int yIdx = indexOf(columns, "Y좌표");
            if (routeIdx < 0 || seqIdx < 0 || nodeIdx < 0) {
                return Map.of();
            }
            String line;
            while ((line = reader.readLine()) != null) {
                String[] cells = line.split(",", -1);
                String routeId = cell(cells, routeIdx);
                String nodeId = cell(cells, nodeIdx);
                if (routeId.isEmpty() || nodeId.isEmpty()) {
                    continue;
                }
                Integer seq = parseIntOrNull(cell(cells, seqIdx));
                String name = cell(cells, nameIdx);
                Double lng = parseDoubleOrNull(cell(cells, xIdx));
                Double lat = parseDoubleOrNull(cell(cells, yIdx));
                routes.computeIfAbsent(routeId, key -> new ArrayList<>())
                        .add(new RouteStop(nodeId, name.isEmpty() ? null : name, seq, lat, lng));
            }
        } catch (IOException e) {
            return Map.of();
        }
        Map<String, List<RouteStop>> out = new LinkedHashMap<>();
        for (Map.Entry<String, List<RouteStop>> entry : routes.entrySet()) {
            out.put(entry.getKey(), List.copyOf(entry.getValue()));
        }
        return Map.copyOf(out);
    }

    private static InputStream resourceStream() throws IOException {
        InputStream in = BusRouteStopsReader.class.getClassLoader()
                .getResourceAsStream(RESOURCE_PATH);
        if (in == null) {
            throw new IOException("원천 없음: " + RESOURCE_PATH);
        }
        return in;
    }

    private static int indexOf(String[] columns, String name) {
        for (int i = 0; i < columns.length; i++) {
            if (columns[i].trim().equals(name)) {
                return i;
            }
        }
        return -1;
    }

    private static String cell(String[] cells, int idx) {
        if (idx < 0 || idx >= cells.length) {
            return "";
        }
        return cells[idx].trim();
    }

    private static Integer parseIntOrNull(String value) {
        try {
            return Integer.valueOf(value);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Double parseDoubleOrNull(String value) {
        try {
            return Double.valueOf(value);
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
