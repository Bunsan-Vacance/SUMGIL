package com.ssafy.s15p21a104.load.subway;

import com.ssafy.s15p21a104.load.Coords;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * KTDB 철도망 노드(data/railgeometry/ktdb-rail-node_2024.csv, 전국 1,652개, 63 에서 도입) → 이름별 역 좌표.
 * 국가철도공단 역위치 파일에 좌표가 없거나 무효인 역의 마지막 보완 원천이다. 노선 코드는 없으므로(null) 이름으로만 대조한다.
 * <p>
 * 선로 노드라 역 하나에 노드가 2개(승강장·방향별)일 수 있어 평균점을 쓴다(실측 차이 수십~250 m). 전국 데이터라 수도권 범위 밖
 * 동명 노드(부산·여수 등)는 걸러낸다. 이름은 괄호 부기와 끝의 '역'을 떼고 별칭을 적용한다 ("석남(거북시장)역" → 석남).
 */
public final class KtdbNodeCoordParser {

    private final StationNameNormalizer normalizer;

    public KtdbNodeCoordParser(StationNameNormalizer normalizer) {
        this.normalizer = normalizer;
    }

    public List<StationCoord> parse(List<Map<String, String>> rows) {
        Map<String, List<double[]>> byName = new LinkedHashMap<>();
        for (Map<String, String> row : rows) {
            String raw = value(row, "station_name_raw");
            if (raw.isEmpty()) {
                continue;
            }
            Double lat;
            Double lng;
            try {
                lat = Coords.parseOrNull(row.get("lat"));
                lng = Coords.parseOrNull(row.get("lng"));
            } catch (NumberFormatException e) {
                continue;
            }
            if (lat == null || lng == null || !Coords.inMetroArea(lat, lng)) {
                continue;
            }
            byName.computeIfAbsent(normalizeName(raw), k -> new ArrayList<>()).add(new double[] {lat, lng});
        }
        List<StationCoord> out = new ArrayList<>(byName.size());
        for (Map.Entry<String, List<double[]>> e : byName.entrySet()) {
            double lat = e.getValue().stream().mapToDouble(p -> p[0]).average().orElseThrow();
            double lng = e.getValue().stream().mapToDouble(p -> p[1]).average().orElseThrow();
            out.add(new StationCoord(null, e.getKey(), lat, lng, null));
        }
        return out;
    }

    private String normalizeName(String raw) {
        String name = normalizer.normalize(raw);
        if (name.length() > 1 && name.endsWith("역")) {
            name = normalizer.normalize(name.substring(0, name.length() - 1));
        }
        return name;
    }

    /** 이 파서는 결함 행을 조용히 건너뛴다(전국 데이터의 대부분이 범위 밖). 경고 목록은 비어 있다. */
    public List<String> warnings() {
        return List.of();
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }
}
