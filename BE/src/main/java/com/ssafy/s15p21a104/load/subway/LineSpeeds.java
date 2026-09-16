package com.ssafy.s15p21a104.load.subway;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 노선별 표정속도 표 — data/subway/conf/line-speeds.csv (`line_id, mps, 근거`).
 * 거리만 있는 구간(시각표가 없는 노선, source=avg)의 소요시간을 거리 ÷ 속도로 추정할 때 쓴다.
 * 값은 운영사·언론이 공표한 전 구간 소요시간 ÷ KTDB 링크 경로 거리라 정차시간이 포함된 표정속도다.
 * 표에 없는 노선은 기본값(load.avg-speed-mps, 서울교통공사 1.1 km ≈ 2분 기준 9.2)으로 떨어진다.
 */
public final class LineSpeeds {

    private final Map<String, Double> byLine;
    private final double fallbackMps;

    private LineSpeeds(Map<String, Double> byLine, double fallbackMps) {
        this.byLine = byLine;
        this.fallbackMps = fallbackMps;
    }

    /**
     * @param rows        conf 행. line_id 가 비었거나 겹치거나 mps 가 0 이하·숫자가 아니면 IllegalArgumentException — 조용히 기본값으로 넘어가지 않게
     * @param fallbackMps 표에 없는 노선의 속도 (m/s)
     */
    public static LineSpeeds from(List<Map<String, String>> rows, double fallbackMps) {
        Map<String, Double> byLine = new LinkedHashMap<>();
        for (Map<String, String> row : rows) {
            String lineId = value(row, "line_id");
            String mps = value(row, "mps");
            if (lineId.isEmpty()) {
                throw new IllegalArgumentException("line_id 가 빈 행: " + row);
            }
            double speed;
            try {
                speed = Double.parseDouble(mps);
            } catch (NumberFormatException e) {
                throw new IllegalArgumentException("표정속도가 숫자가 아님: " + lineId + " '" + mps + "'");
            }
            if (!(speed > 0)) {
                throw new IllegalArgumentException("표정속도는 0 보다 커야 함: " + lineId + " " + mps);
            }
            if (byLine.put(lineId, speed) != null) {
                throw new IllegalArgumentException("노선이 두 번 나옴: " + lineId);
            }
        }
        return new LineSpeeds(byLine, fallbackMps);
    }

    /** 표의 값, 없으면 기본값 (m/s). */
    public double speedOf(String lineId) {
        return byLine.getOrDefault(lineId, fallbackMps);
    }

    /** 표에 없어 기본값을 쓰는 노선인가. */
    public boolean isDefault(String lineId) {
        return !byLine.containsKey(lineId);
    }

    public Map<String, Double> table() {
        return Collections.unmodifiableMap(byLine);
    }

    public double fallbackMps() {
        return fallbackMps;
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }
}
