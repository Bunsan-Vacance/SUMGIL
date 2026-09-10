package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * 국토교통부 "도시철도 전체노선"(공공데이터포털 15122916, data/subway/molit-urban-lines_*.csv) → 노선별 역 목록.
 * 열은 `권역 · 권역명 · 철도운영기관명 · 노선명 · 순번 · 역명`. 수도권 행만 읽고 노선명을 {@link LineCodes#fromUrbanLineName} 으로 바꾼다.
 * <p>
 * 순번은 지선에서 중복된다(경의중앙 21 = 수색·신촌, 경춘 5 = 광운대·망우). 그래서 인접 관계는 KTDB 링크가 정하고,
 * 이 파일은 "그 노선에 어떤 역이 있어야 하는가" 를 대조하는 데만 쓴다 — 링크에 없는 역(광운대 지선), 파일에 없는 역(서해선 원종)이 경고로 드러난다.
 */
public final class UrbanLineParser {

    private static final String METRO_REGION = "수도권";

    private final StationNameNormalizer normalizer;
    private final List<String> warnings = new ArrayList<>();

    public UrbanLineParser(StationNameNormalizer normalizer) {
        this.normalizer = normalizer;
    }

    /** @return line_id → 정규화 역명 목록 (파일 순서, 중복 제거) */
    public Map<String, List<String>> parse(List<Map<String, String>> rows) {
        warnings.clear();
        Map<String, LinkedHashSet<String>> byLine = new LinkedHashMap<>();
        Set<String> unknownLines = new LinkedHashSet<>();
        for (Map<String, String> row : rows) {
            if (!METRO_REGION.equals(value(row, "권역명"))) {
                continue;
            }
            String lineName = value(row, "노선명");
            Optional<String> lineId = LineCodes.fromUrbanLineName(lineName);
            if (lineId.isEmpty()) {
                unknownLines.add(lineName);
                continue;
            }
            // 서해선 행은 "김포공항역"처럼 '역'을 붙여 적는다 — KTDB 노드·표준데이터와 같은 규칙으로 뗀다
            byLine.computeIfAbsent(lineId.get(), k -> new LinkedHashSet<>()).add(normalizer.normalizeStation(value(row, "역명")));
        }
        if (!unknownLines.isEmpty()) {
            warnings.add("line_id 가 없는 노선 " + unknownLines.size() + "개 건너뜀 (실시간 API 코드 없음): " + String.join(", ", unknownLines));
        }
        Map<String, List<String>> out = new LinkedHashMap<>();
        byLine.forEach((line, names) -> out.put(line, List.copyOf(names)));
        return out;
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }
}
