package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 서울교통공사 "역간거리 및 소요시간" 파일 → 구간 목록.
 * 파일은 호선별로 역을 운행 순서대로 나열하며 소요시간은 직전 역에서 이 역까지다.
 * - 소요시간 00:00 은 노선 시작점 (구간 없음)
 * - 순환선은 마지막 행이 첫 역으로 돌아오며 그것도 구간이다
 * - 지선 첫 역은 직전 행이 아니라 분기역에 붙는다 (branchAnchors: lineId → {지선 첫 역 → 분기역})
 */
public final class SeoulMetroTimetableParser {

    private final StationNameNormalizer normalizer;
    private final Map<String, Map<String, String>> branchAnchors;
    private final List<String> warnings = new ArrayList<>();

    public SeoulMetroTimetableParser(StationNameNormalizer normalizer, Map<String, Map<String, String>> branchAnchors) {
        this.normalizer = normalizer;
        this.branchAnchors = Map.copyOf(branchAnchors);
    }

    public List<Segment> parse(List<Map<String, String>> rows) {
        List<Segment> out = new ArrayList<>();
        String prevLine = null;
        String prevStation = null;

        for (Map<String, String> row : rows) {
            String lineId = LineCodes.fromSeoulMetroLine(row.get("호선")).orElse(null);
            if (lineId == null) {
                warnings.add("호선 표기를 모름: " + row.get("호선") + " (" + row.get("역명") + ")");
                continue;
            }
            String station = normalizer.normalize(row.get("역명"));
            int travelSec = parseMmSs(row.get("소요시간"));
            int distanceM = parseKmToMeters(row.get("역간거리(km)"));

            if (!lineId.equals(prevLine)) {
                prevLine = lineId;
                prevStation = null;
            }
            if (travelSec == 0) {
                prevStation = station;
                continue;
            }
            String anchor = branchAnchors.getOrDefault(lineId, Map.of()).get(station);
            String from = anchor != null ? anchor : prevStation;
            if (from == null) {
                warnings.add("출발 역을 알 수 없음: " + lineId + " " + station);
                prevStation = station;
                continue;
            }
            out.add(new Segment(lineId, from, station, travelSec, distanceM, "timetable"));
            prevStation = station;
        }
        return out;
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    /** "02:13" → 133. 빈 값은 0. */
    public static int parseMmSs(String text) {
        if (text == null || text.isBlank()) {
            return 0;
        }
        String[] parts = text.trim().split(":");
        if (parts.length != 2) {
            throw new IllegalArgumentException("mm:ss 형식이 아님: " + text);
        }
        return Integer.parseInt(parts[0]) * 60 + Integer.parseInt(parts[1]);
    }

    private static int parseKmToMeters(String text) {
        if (text == null || text.isBlank()) {
            return 0;
        }
        return (int) Math.round(Double.parseDouble(text.trim()) * 1000);
    }
}
