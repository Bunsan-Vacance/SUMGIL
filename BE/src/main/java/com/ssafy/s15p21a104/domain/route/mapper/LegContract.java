package com.ssafy.s15p21a104.domain.route.mapper;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.TransitionType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Set;

/**
 * 구간 전환 구분·대여소 식별 부착(S15P21A104-237, FE-BE 통합 계약 §3).
 *
 * <p>순수 함수이며 DB·Spring에 의존하지 않는다. TRANSFER 모드 구간에만
 * 승차·하차·환승을 매기고, BIKE 구간에만 대여·반납과 대여소 ID를 매긴다.
 * 나머지는 null이다 — FE가 의미를 추측하지 않게 한다.
 */
public final class LegContract {

    private LegContract() {
    }

    /**
     * @param legs 원본 구간 목록(순서 유지)
     * @param rentalIds 대여소 ID 집합. null이면 빈 집합
     * @return 전환 구분·대여소 ID가 채워진 구간 목록(같은 순서·개수)
     */
    public static List<RouteLegResponse> withContractFields(
            List<RouteLegResponse> legs, Set<String> rentalIds) {
        Objects.requireNonNull(legs, "legs");
        Set<String> rentals = rentalIds == null ? Set.of() : rentalIds;
        boolean[] transitAfter = new boolean[legs.size()];
        boolean seen = false;
        for (int i = legs.size() - 1; i >= 0; i--) {
            transitAfter[i] = seen;
            if (isTransit(legs.get(i).mode())) {
                seen = true;
            }
        }
        List<RouteLegResponse> out = new ArrayList<>(legs.size());
        boolean transitBefore = false;
        for (int i = 0; i < legs.size(); i++) {
            RouteLegResponse leg = legs.get(i);
            TransitionType type = transitionTypeOf(leg, transitBefore, transitAfter[i], rentals);
            out.add(new RouteLegResponse(
                    leg.mode(), leg.fromNodeId(), leg.fromNodeName(), leg.fromLat(), leg.fromLng(),
                    leg.toNodeId(), leg.toNodeName(), leg.toLat(), leg.toLng(),
                    leg.routeId(), leg.minutes(), leg.geometry(), leg.geometryStatus(),
                    leg.distanceMeters(), leg.routeName(), leg.routeOptions(),
                    leg.congestionGrade(),
                    type,
                    rentals.contains(leg.fromNodeId()) ? leg.fromNodeId() : null,
                    rentals.contains(leg.toNodeId()) ? leg.toNodeId() : null));
            if (isTransit(leg.mode())) {
                transitBefore = true;
            }
        }
        return List.copyOf(out);
    }

    private static TransitionType transitionTypeOf(RouteLegResponse leg,
            boolean transitBefore, boolean transitAfter, Set<String> rentals) {
        if (leg.mode() == TravelMode.TRANSFER) {
            if (!transitBefore) {
                return TransitionType.BOARDING;
            }
            if (!transitAfter) {
                return TransitionType.ALIGHTING;
            }
            return TransitionType.TRANSFER;
        }
        if (leg.mode() == TravelMode.BIKE) {
            if (rentals.contains(leg.fromNodeId())) {
                return TransitionType.BIKE_RENTAL;
            }
            if (rentals.contains(leg.toNodeId())) {
                return TransitionType.BIKE_RETURN;
            }
        }
        return null;
    }

    private static boolean isTransit(TravelMode mode) {
        return mode == TravelMode.SUBWAY || mode == TravelMode.BUS;
    }
}
