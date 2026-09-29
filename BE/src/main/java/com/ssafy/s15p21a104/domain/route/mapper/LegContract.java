package com.ssafy.s15p21a104.domain.route.mapper;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteOptionResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.TransitionType;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.ArrayList;
import java.util.HashSet;
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
                    leg.routeId(), leg.minutes(), leg.waitMinutes(),
                    leg.geometry(), leg.geometryStatus(),
                    leg.distanceMeters(), leg.routeName(), leg.routeOptions(),
                    leg.congestionGrade(),
                    type,
                    rentals.contains(leg.fromNodeId()) ? leg.fromNodeId() : null,
                    rentals.contains(leg.toNodeId()) ? leg.toNodeId() : null,
                    leg.congestionLevel()));
            if (isTransit(leg.mode())) {
                transitBefore = true;
            }
        }
        return List.copyOf(out);
    }

    /**
     * 실제 탑승 수단 순서로 사용자에게 표시할 환승 횟수를 센다.
     *
     * <p>WALK와 TRANSFER 자체는 탑승으로 세지 않는다. BUS는 구간별 운행 노선 후보의
     * 누적 교집합으로 같은 버스를 계속 탈 수 있는지 판정하고, 명시적인 TRANSFER는
     * 다음 실제 탑승 경계에서 한 번 보조한다.</p>
     */
    public static int userTransferCount(List<RouteLegResponse> legs) {
        Objects.requireNonNull(legs, "legs");
        int count = 0;
        boolean pendingTransfer = false;
        Boarding previous = null;
        for (RouteLegResponse leg : legs) {
            Objects.requireNonNull(leg, "legs contains null");
            if (leg.mode() == TravelMode.TRANSFER) {
                if (leg.transitionType() == TransitionType.TRANSFER) {
                    pendingTransfer = true;
                }
                continue;
            }
            if (!isBoardingMode(leg.mode())) {
                continue;
            }

            Boarding current = boardingOf(leg);
            if (previous != null) {
                if (pendingTransfer || transferBoundary(previous, current)) {
                    count++;
                }
            }
            boolean resetBusOptions = pendingTransfer;
            pendingTransfer = false;
            previous = carryBusOptions(previous, current, resetBusOptions);
        }
        return count;
    }

    private record Boarding(TravelMode mode, String routeId, Set<String> busOptions) {
    }

    private static Boarding boardingOf(RouteLegResponse leg) {
        Set<String> busOptions = leg.mode() == TravelMode.BUS ? busOptionsOf(leg) : null;
        return new Boarding(leg.mode(), knownRouteId(leg.routeId()), busOptions);
    }

    private static boolean transferBoundary(Boarding previous, Boarding current) {
        if (previous.mode() != current.mode()) {
            return true;
        }
        if (current.mode() == TravelMode.BUS) {
            if (previous.busOptions() == null || current.busOptions() == null) {
                return false;
            }
            return java.util.Collections.disjoint(previous.busOptions(), current.busOptions());
        }
        if (current.mode() == TravelMode.BIKE) {
            return false;
        }
        if (previous.routeId() == null || current.routeId() == null) {
            return false;
        }
        return !previous.routeId().equals(current.routeId());
    }

    private static Boarding carryBusOptions(Boarding previous, Boarding current,
            boolean resetBusOptions) {
        if (previous == null || previous.mode() != TravelMode.BUS
                || current.mode() != TravelMode.BUS
                || previous.busOptions() == null || current.busOptions() == null) {
            return current;
        }
        if (resetBusOptions) {
            return current;
        }
        Set<String> intersection = new HashSet<>(previous.busOptions());
        intersection.retainAll(current.busOptions());
        return new Boarding(current.mode(), current.routeId(),
                intersection.isEmpty() ? current.busOptions() : Set.copyOf(intersection));
    }

    private static boolean isBoardingMode(TravelMode mode) {
        return mode == TravelMode.BIKE || mode == TravelMode.BUS || mode == TravelMode.SUBWAY;
    }

    private static String knownRouteId(String routeId) {
        if (routeId == null || routeId.isBlank()) {
            return null;
        }
        return routeId;
    }

    private static Set<String> busOptionsOf(RouteLegResponse leg) {
        Set<String> options = new HashSet<>();
        List<RouteOptionResponse> routeOptions = leg.routeOptions();
        if (routeOptions != null) {
            for (RouteOptionResponse option : routeOptions) {
                if (option != null && knownRouteId(option.routeId()) != null) {
                    options.add(option.routeId());
                }
            }
        }
        if (!options.isEmpty()) {
            return Set.copyOf(options);
        }
        String routeId = knownRouteId(leg.routeId());
        if (routeId == null || BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID.equals(routeId)) {
            return null;
        }
        return Set.of(routeId);
    }

    private static TransitionType transitionTypeOf(RouteLegResponse leg,
            boolean transitBefore, boolean transitAfter, Set<String> rentals) {
        // FE 검증이 transitionType을 TRANSFER 모드에서만 허용한다(2026-09-21 prod 장애).
        // BIKE_RENTAL·BIKE_RETURN 값은 계약에 있으나 BIKE 구간에 달면 FE가 응답을 버리므로
        // 달지 않는다 — 대여·반납 의미는 from/toRentalId로 전달한다. FE와 위치 협의 후 재결정.
        if (leg.mode() == TravelMode.TRANSFER) {
            if (!transitBefore) {
                return TransitionType.BOARDING;
            }
            if (!transitAfter) {
                return TransitionType.ALIGHTING;
            }
            return TransitionType.TRANSFER;
        }
        return null;
    }

    private static boolean isTransit(TravelMode mode) {
        return mode == TravelMode.SUBWAY || mode == TravelMode.BUS;
    }
}
