package com.ssafy.s15p21a104.load.subway;

import com.ssafy.s15p21a104.load.Coords;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * 국가철도공단 노선별 "역위치" 파일(공공데이터포털 15041300 등, data/subway/kric/) → 노선별 역 좌표.
 * 열은 `철도운영기관(명) · 선명 · 역명 · 경도 · 위도`. 서울교통공사 좌표 파일이 덮지 않는 코레일·연장 구간 역(148개)의 주 원천이다.
 * <p>
 * 원천 결함을 고쳐 넣지 않는다: 7호선 파일의 부천·인천 구간 11역은 0,0 이고 3호선 원흥은 위도에 소수점이 빠져 있다(37650709).
 * 이런 무효 좌표는 건너뛰고 한 줄로 집계 경고한다 — 그 역은 다음 원천(KTDB 노드)이 채운다.
 */
public final class KricStationCoordParser {

    private static final int EXAMPLE_LIMIT = 12;

    private final StationNameNormalizer normalizer;
    private final List<String> warnings = new ArrayList<>();
    private final Set<String> unknownLines = new HashSet<>();
    private int skipped;

    public KricStationCoordParser(StationNameNormalizer normalizer) {
        this.normalizer = normalizer;
    }

    /** 파일 하나의 행. 여러 파일을 같은 인스턴스로 이어 호출하면 경고·건너뜀 수가 누적된다. */
    public List<StationCoord> parse(List<Map<String, String>> rows) {
        Map<String, StationCoord> out = new LinkedHashMap<>();
        List<String> invalid = new ArrayList<>();
        for (Map<String, String> row : rows) {
            String lineName = value(row, "선명");
            String name = normalizer.normalize(value(row, "역명"));
            Double lat;
            Double lng;
            try {
                lat = Coords.parseOrNull(row.get("위도"));
                lng = Coords.parseOrNull(row.get("경도"));
            } catch (NumberFormatException e) {
                lat = null;
                lng = null;
            }
            if (lat == null || lng == null || (lat == 0 && lng == 0) || !Coords.inMetroArea(lat, lng)) {
                skipped++;
                invalid.add(name + "(" + value(row, "위도") + "," + value(row, "경도") + ")");
                continue;
            }
            String lineId = lineIdOf(lineName);
            String key = lineId + "|" + name;
            StationCoord existing = out.get(key);
            if (existing == null) {
                out.put(key, new StationCoord(lineId, name, lat, lng, null));
            } else if (existing.lat() != lat || existing.lng() != lng) {
                warnings.add("같은 (선, 역)에 다른 좌표: " + lineName + " " + name + " — 첫 값을 쓴다");
            }
        }
        if (!invalid.isEmpty()) {
            warnings.add("무효 좌표 " + invalid.size() + "건 건너뜀 (0,0 · 범위 밖 · 형식 오류 — 다음 원천이 채움): " + head(invalid));
        }
        return List.copyOf(out.values());
    }

    /** "1호선" → 1001, "경의중앙" → 1063 ('선' 이 빠진 표기는 붙여서 재시도). 모르면 null 로 두고 이름으로만 쓴다. */
    private String lineIdOf(String lineName) {
        Optional<String> id = LineCodes.fromName(lineName);
        if (id.isEmpty() && !lineName.endsWith("선")) {
            id = LineCodes.fromName(lineName + "선");
        }
        if (id.isEmpty()) {
            if (unknownLines.add(lineName)) {
                warnings.add("모르는 선명: '" + lineName + "' — 노선 코드 없이 이름으로만 쓴다");
            }
            return null;
        }
        return id.get();
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    /** 무효 좌표로 건너뛴 행 수 (누적). */
    public int skipped() {
        return skipped;
    }

    private static String head(List<String> items) {
        String joined = String.join(", ", items.subList(0, Math.min(EXAMPLE_LIMIT, items.size())));
        return items.size() > EXAMPLE_LIMIT ? joined + ", …" : joined;
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }
}
