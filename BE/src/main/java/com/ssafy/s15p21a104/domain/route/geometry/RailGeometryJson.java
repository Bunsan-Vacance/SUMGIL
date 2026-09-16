package com.ssafy.s15p21a104.domain.route.geometry;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ssafy.s15p21a104.domain.route.entity.RailLinkGeometry;

import java.util.List;

/** {@code rail_link_geometry.geometry}(GeoJSON LineString 문자열)를 좌표 배열로 읽는다. */
final class RailGeometryJson {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private RailGeometryJson() {
    }

    private record LineString(String type, List<List<Double>> coordinates) {
    }

    static List<List<Double>> coordinates(RailLinkGeometry link) {
        try {
            return MAPPER.readValue(link.getGeometry(), LineString.class).coordinates();
        } catch (Exception e) {
            throw new IllegalStateException("KTDB geometry 파싱 실패: link_id=" + link.getLinkId(), e);
        }
    }
}
