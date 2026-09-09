package com.ssafy.s15p21a104.domain.route.dto.response;

import java.util.List;

/**
 * GeoJSON MultiLineString. KTDB link 여러 개를 이어붙인 결과이며, 하나의 연속된 선으로 합치지 않고
 * link 단위 좌표 배열을 그대로 배열에 담는다(FE 제안 계약, 아직 미승인 — BE/scripts/railgeometry/README.md 참고).
 */
public record MultiLineStringResponse(
        String type,
        List<List<List<Double>>> coordinates
) {
    public static MultiLineStringResponse of(List<List<List<Double>>> coordinates) {
        return new MultiLineStringResponse("MultiLineString", coordinates);
    }
}
