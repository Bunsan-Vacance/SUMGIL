package com.ssafy.s15p21a104.load.subway;

import com.ssafy.s15p21a104.load.Coords;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 전국도시철도역사정보표준데이터(공공데이터포털 15013205, data/subway/kric-station-standard_*.csv) → 노선별 역 좌표.
 * 열은 `역번호 · 역사명 · 노선번호 · 노선명 · … · 역위도 · 역경도 · 운영기관명`. 전국 파일이라 수도권 범위 밖 행(부산·대구의 동명역)은 건너뛴다.
 * <p>
 * 국가철도공단 역위치 파일이 없는 노선(경춘·경강·서해·공항·신분당·우이신설·신림)의 좌표 원천이고, 역번호(externalCode)는
 * station-ids 표에서 코레일·사철 전용 역의 station_id 정본이다. 노선번호는 {@link LineCodes#fromStdLineCode} 로 바꾸되,
 * 물리 선로 공용 코드(경원선 I4102)는 line_id 없이(null) 이름으로만 대조한다. 역명은 "청량리역"처럼 '역'이 붙어 있어 뗀다.
 */
public final class StdStationParser {

    private final StationNameNormalizer normalizer;
    private final List<String> warnings = new ArrayList<>();
    private int skipped;

    public StdStationParser(StationNameNormalizer normalizer) {
        this.normalizer = normalizer;
    }

    public List<StationCoord> parse(List<Map<String, String>> rows) {
        Map<String, StationCoord> out = new LinkedHashMap<>();
        for (Map<String, String> row : rows) {
            String name = normalizer.normalizeStation(value(row, "역사명"));
            Double lat;
            Double lng;
            try {
                lat = Coords.parseOrNull(row.get("역위도"));
                lng = Coords.parseOrNull(row.get("역경도"));
            } catch (NumberFormatException e) {
                lat = null;
                lng = null;
            }
            if (name.isEmpty() || lat == null || lng == null || !Coords.inMetroArea(lat, lng)) {
                skipped++;
                continue;
            }
            String lineId = LineCodes.fromStdLineCode(value(row, "노선번호")).orElse(null);
            String key = lineId + "|" + name;
            if (!out.containsKey(key)) {
                out.put(key, new StationCoord(lineId, name, lat, lng, value(row, "역번호")));
            }
        }
        return List.copyOf(out.values());
    }

    /** 수도권 밖·좌표 없음으로 건너뛴 행 수 (전국 파일이라 대부분이 여기 해당한다). */
    public int skipped() {
        return skipped;
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }
}
