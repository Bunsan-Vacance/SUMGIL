package com.ssafy.s15p21a104.domain.route.dto.response;

import java.util.List;

/**
 * BUS leg 운행 노선 후보 1건(S15P21A104-234). 탐색은 구간 단위라 노선 선택을 미루고
 * 후보 전부를 싣는다. FE는 목록 표시용으로만 쓴다.
 */
public record RouteOptionResponse(
        /** 노선 ID. */
        String routeId,
        /** 사람이 읽는 노선 이름(버스 번호). 미확보면 null. */
        String routeName,
        /** 배차간격(분). 미확보면 null (0으로 바꾸지 않는다). */
        Integer headwayMin
) {
    public static List<RouteOptionResponse> of(
            List<String> routeIds, java.util.Map<String, String> names,
            java.util.Map<String, Integer> headways) {
        return routeIds.stream()
                .map(id -> new RouteOptionResponse(id, names.get(id), headways.get(id)))
                .toList();
    }
}
