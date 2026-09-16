package com.ssafy.s15p21a104.domain.route.graph;

import java.util.Map;
import java.util.Optional;

/**
 * 역 ID·노선 ID의 이름 해석(이름 매핑).
 *
 * <p>{@code station.name}·{@code line.name}에서 조회한 결과를 받아 이름을 제공한다.
 * 경로 응답(legs의 fromName·toName·lineName 등)을 만들 때 사용한다.
 * 미등록 ID는 {@link Optional#empty()}로 부재를 정확히 보고한다.
 */
public final class RouteNameMapper {

    /** 역 ID별 역 이름. */
    private final Map<String, String> stationNames;

    /** 노선 ID별 노선 이름. */
    private final Map<String, String> lineNames;

    /**
     * 이름 매핑을 만든다. 입력 맵은 복사해 불변으로 보관한다.
     *
     * @param stationNames 역 ID별 역 이름
     * @param lineNames 노선 ID별 노선 이름
     */
    public RouteNameMapper(Map<String, String> stationNames, Map<String, String> lineNames) {
        this.stationNames = stationNames == null ? Map.of() : Map.copyOf(stationNames);
        this.lineNames = lineNames == null ? Map.of() : Map.copyOf(lineNames);
    }

    /**
     * 역 ID로 역 이름 조회.
     *
     * @param stationId 역 ID
     * @return 역 이름(미등록이면 빈 값)
     */
    public Optional<String> stationNameOf(String stationId) {
        if (stationId == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(stationNames.get(stationId));
    }

    /**
     * 노선 ID로 노선 이름 조회.
     *
     * @param lineId 노선 ID
     * @return 노선 이름(미등록이면 빈 값)
     */
    public Optional<String> lineNameOf(String lineId) {
        if (lineId == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(lineNames.get(lineId));
    }
}
