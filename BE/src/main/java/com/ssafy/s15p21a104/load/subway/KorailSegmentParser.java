package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 공공데이터포털 "서울시 도시철도 구간정보"(코레일 광역 구간) → 구간 목록.
 * 거리(m)만 있고 소요시간이 없어 표정속도로 추정하고 source='avg' 로 표시한다.
 * 시간표 값이 생기면 같은 키의 행을 timetable 로 덮어쓴다.
 */
public final class KorailSegmentParser {

    /** 아주 짧은 구간이 0초가 되지 않게 하는 하한. */
    static final int MIN_TRAVEL_SEC = 30;

    private final StationNameNormalizer normalizer;
    private final double avgSpeedMps;
    private final Map<String, List<String>> lineOverrides;
    private final List<String> warnings = new ArrayList<>();

    /**
     * @param avgSpeedMps 정차 포함 표정속도 (m/s). 서울교통공사 시간표에서 1.1 km 구간이 2분이라 9.2 m/s 가 기준값이다.
     */
    public KorailSegmentParser(StationNameNormalizer normalizer, double avgSpeedMps) {
        this(normalizer, avgSpeedMps, Map.of());
    }

    /**
     * @param lineOverrides "출발역|도착역"(정규화 표기) → 이 구간이 속하는 서비스 노선 목록.
     *                      파일의 노선 코드는 물리 선로 기준(경원선 103 등)이라 서비스 노선과 어긋나는 구간을 바로잡는다.
     *                      한 선로를 두 노선이 함께 쓰면(청량리~회기) 노선마다 구간을 하나씩 만든다.
     */
    public KorailSegmentParser(StationNameNormalizer normalizer, double avgSpeedMps, Map<String, List<String>> lineOverrides) {
        this.normalizer = normalizer;
        this.avgSpeedMps = avgSpeedMps;
        this.lineOverrides = Map.copyOf(lineOverrides);
    }

    public List<Segment> parse(List<Map<String, String>> rows) {
        List<Segment> out = new ArrayList<>();
        for (Map<String, String> row : rows) {
            String from = normalizer.normalize(row.get("출발_역_명칭"));
            String to = normalizer.normalize(row.get("도착_역_명칭"));
            List<String> lineIds = lineOverrides.get(from + "|" + to);
            if (lineIds == null) {
                String byCode = LineCodes.fromKorailCode(row.get("출발_호선_내용")).orElse(null);
                if (byCode == null) {
                    warnings.add("노선 코드를 모름: " + row.get("출발_호선_내용") + " (" + from + " → " + to + ")");
                    continue;
                }
                lineIds = List.of(byCode);
            }
            int meters = Integer.parseInt(row.get("거리").trim());
            int travelSec = Math.max(MIN_TRAVEL_SEC, (int) Math.round(meters / avgSpeedMps));
            for (String lineId : lineIds) {
                out.add(new Segment(lineId, from, to, travelSec, meters, "avg"));
            }
        }
        return out;
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }
}
