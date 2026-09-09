package com.ssafy.s15p21a104.load.railgeometry;

/** KTDB 철도교차점(node) 1행. {@code convert_ktdb.py}가 만든 CSV 그대로 매핑한다. */
public record RailNodeRow(
        String nodeId,
        Double lat,
        Double lng,
        String stationNameRaw
) {
}
