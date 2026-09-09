package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 서울교통공사 "환승역거리 소요시간" 파일 → 환승 레코드.
 * 1~8호선 쪽에서만 기록되므로 반대 방향이 없으면 같은 값으로 만들어 준다.
 * 상대 노선 표기를 모르면 건너뛰고 경고로 남긴다.
 */
public final class TransferParser {

    private final StationNameNormalizer normalizer;
    private final List<String> warnings = new ArrayList<>();

    public TransferParser(StationNameNormalizer normalizer) {
        this.normalizer = normalizer;
    }

    public List<TransferRecord> parse(List<Map<String, String>> rows) {
        Map<String, TransferRecord> byKey = new LinkedHashMap<>();
        for (Map<String, String> row : rows) {
            String fromLine = LineCodes.fromSeoulMetroLine(row.get("호선")).orElse(null);
            String toLine = LineCodes.fromName(row.get("환승노선")).orElse(null);
            String station = normalizer.normalize(row.get("환승역명"));
            if (fromLine == null || toLine == null) {
                warnings.add("노선 표기를 모름: " + station + " " + row.get("호선") + "호선 → " + row.get("환승노선"));
                continue;
            }
            int walkSec = parseMmSs(row.get("환승소요시간"));
            byKey.putIfAbsent(key(station, fromLine, toLine), new TransferRecord(station, fromLine, toLine, walkSec));
        }

        List<TransferRecord> out = new ArrayList<>(byKey.values());
        for (TransferRecord r : List.copyOf(out)) {
            String reverseKey = key(r.stationName(), r.toLineId(), r.fromLineId());
            if (!byKey.containsKey(reverseKey)) {
                TransferRecord reverse = new TransferRecord(r.stationName(), r.toLineId(), r.fromLineId(), r.walkSec());
                byKey.put(reverseKey, reverse);
                out.add(reverse);
            }
        }
        return out;
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    private static String key(String station, String from, String to) {
        return station + "|" + from + "|" + to;
    }

    /** "02:13" → 133. 빈 값은 0. (역간거리 파서가 시각표로 대체되면서 여기로 옮겼다) */
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
}
