package com.ssafy.s15p21a104.load.railgeometry;

/**
 * KTDB 철도중심선(link) 1행.
 *
 * @param lineNameRaw         KTDB RAILLINEN3 (지하철·도시철도 서비스명, 예: "서울2호선")
 * @param physicalLineNameRaw KTDB RAILLINE_N (물리 선로명, 예: "경부선"). 참고용
 * @param lineId              {@code line.line_id} 매칭 결과. 못 찾으면 null(우리 노선표 밖)
 */
public record RailLinkGeometryRow(
        String linkId,
        String fromNodeId,
        String toNodeId,
        String lineNameRaw,
        String physicalLineNameRaw,
        String lineId,
        Double lengthKm,
        String geometryGeojson
) {
}
