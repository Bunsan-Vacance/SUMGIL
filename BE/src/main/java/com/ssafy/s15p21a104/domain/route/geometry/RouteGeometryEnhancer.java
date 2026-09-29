package com.ssafy.s15p21a104.domain.route.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Function;

/**
 * 후보별 geometry 후처리(S15P21A104-213 T3).
 *
 * <p>{@code RouteSearchService}에서 분리했다. 후보 목록을 받아 각 후보의 legs에
 * geometry를 붙인다. 후보 간에는 병렬로 처리하고 순서는 유지한다.
 * 한 후보의 geometry 조회가 실패해도(예외) 다른 후보는 그대로 둔다 — 값을
 * 지어내지 않는다는 원칙에 따라 실패한 후보는 geometry 없이 반환한다.
 *
 * <p>조회 함수는 생성자로 주입한다. 레지스트리·DB에 직접 의존하지 않으므로
 * 단위 테스트에서 가짜 조회로 검증할 수 있다.
 */
public final class RouteGeometryEnhancer {

    /** 레일 geometry 조회: (routeId, fromLat, fromLng, toLat, toLng). */
    @FunctionalInterface
    public interface RailGeometryLookup {
        Optional<MultiLineStringResponse> find(
                String routeId, Double fromLat, Double fromLng, Double toLat, Double toLng);
    }

    /** 도보 geometry 조회: (fromId, toId, fromLat, fromLng, toLat, toLng). */
    @FunctionalInterface
    public interface WalkGeometryLookup {
        Optional<MultiLineStringResponse> find(
                String fromId, String toId, Double fromLat, Double fromLng, Double toLat, Double toLng);
    }

    /** 자전거 geometry 조회: (fromId, toId, fromLat, fromLng, toLat, toLng). */
    @FunctionalInterface
    public interface BikeGeometryLookup {
        Optional<MultiLineStringResponse> find(
                String fromId, String toId, Double fromLat, Double fromLng, Double toLat, Double toLng);
    }

    private final RailGeometryLookup railLookup;
    private final WalkGeometryLookup walkLookup;
    private final BikeGeometryLookup bikeLookup;
    private final Function<RouteLegResponse, Optional<MultiLineStringResponse>> busLookup;
    private final ExecutorService executor;

    /**
     * @param railLookup 레일 geometry 조회
     * @param walkLookup 도보 geometry 조회
     * @param bikeLookup 자전거 geometry 조회
     */
    public RouteGeometryEnhancer(
            RailGeometryLookup railLookup, WalkGeometryLookup walkLookup, BikeGeometryLookup bikeLookup) {
        this(railLookup, walkLookup, bikeLookup, leg -> Optional.empty());
    }

    public RouteGeometryEnhancer(
            RailGeometryLookup railLookup, WalkGeometryLookup walkLookup, BikeGeometryLookup bikeLookup,
            Function<RouteLegResponse, Optional<MultiLineStringResponse>> busLookup) {
        this.railLookup = railLookup;
        this.walkLookup = walkLookup;
        this.bikeLookup = bikeLookup;
        this.busLookup = busLookup;
        this.executor = Executors.newVirtualThreadPerTaskExecutor();
    }

    /**
     * 후보 목록 전체에 geometry를 붙인다. 순서를 유지한다.
     *
     * @param candidates geometry 없는 후보 목록
     * @return geometry 후처리된 후보 목록 (같은 순서)
     */
    public List<RouteSearchResponse> enhanceAll(List<RouteSearchResponse> candidates) {
        if (candidates == null || candidates.isEmpty()) {
            return List.of();
        }
        List<CompletableFuture<RouteSearchResponse>> futures = candidates.stream()
                .map(candidate -> CompletableFuture.supplyAsync(
                        () -> enhanceSafely(candidate), executor))
                .toList();
        return futures.stream().map(CompletableFuture::join).toList();
    }

    /** 한 후보 후처리. 예외 나면 원본 그대로 둔다(실패 격리). */
    private RouteSearchResponse enhanceSafely(RouteSearchResponse response) {
        try {
            List<RouteLegResponse> legs = withGeometry(response.legs());
            // 표시 total은 정정된 legs 합으로 맞춘다 — WALK 정정분까지 반영돼야 FE 표시가 어긋나지 않는다.
            // 대기 분리(2026-09-22) 후에는 leg 소요(이동) + waitMinutes 합이다.
            double totalMinutes = legs.stream()
                    .mapToDouble(leg -> leg.minutes()
                            + (leg.waitMinutes() == null ? 0 : leg.waitMinutes()))
                    .sum();
            return new RouteSearchResponse(
                    response.routeType(), totalMinutes, legs, response.source(),
                    totalDistanceOf(legs), response.transferCount(),
                    response.congestionPrediction());
        } catch (RuntimeException e) {
            return response;
        }
    }

    /**
     * leg 목록 전체에 geometry를 붙인다. 연속된 BIKE leg(사이에 WALK·TRANSFER 없이 대여소
     * 경계로만 나뉜 구간, {@link RouteMapper} rentalSplit 참고)는 하나의 실제 이동으로 묶어
     * {@link #withBikeRunGeometry}로 처리한다 — leg마다 독립 호출하면 같은 대여소인데도
     * 카카오 자전거 API의 도로 스냅 진입·이탈점이 달라져 경계가 끊겨 보인다(S15P21A104-153).
     */
    private List<RouteLegResponse> withGeometry(List<RouteLegResponse> legs) {
        List<RouteLegResponse> result = new ArrayList<>();
        int i = 0;
        while (i < legs.size()) {
            if (legs.get(i).mode() != TravelMode.BIKE) {
                result.add(withGeometry(legs.get(i)));
                i++;
                continue;
            }
            int end = i;
            while (end + 1 < legs.size() && legs.get(end + 1).mode() == TravelMode.BIKE) {
                end++;
            }
            result.addAll(withBikeRunGeometry(legs.subList(i, end + 1)));
            i = end + 1;
        }
        return result;
    }

    private RouteLegResponse withGeometry(RouteLegResponse leg) {
        if (leg.fromLat() == null || leg.fromLng() == null || leg.toLat() == null || leg.toLng() == null) {
            return leg;
        }
        if (samePoint(leg)) {
            // 같은 좌표(0m leg, 예: 목적지가 정류장 좌표 그 자체인 접근 구간)는 조회를 하지 않는다 —
            // 유효한 결과가 와도 0m 도보에 외부 경로를 덧붙이면 표시 거리·시간이 왜곡된다.
            return leg;
        }
        Optional<MultiLineStringResponse> geometry = switch (leg.mode()) {
            case WALK -> walkLookup.find(leg.fromNodeId(), leg.toNodeId(),
                    leg.fromLat(), leg.fromLng(), leg.toLat(), leg.toLng());
            case BUS -> busLookup.apply(leg);
            default -> railLookup.find(
                    leg.routeId(), leg.fromLat(), leg.fromLng(), leg.toLat(), leg.toLng());
        };
        if (geometry.isEmpty()) {
            return leg;
        }
        return withGeometry(leg, geometry.get());
    }

    /** 출발·도착이 사실상 같은 점인가(6자리 ≈ 0.1m 미만, 경도 1e-7 ≈ 1cm). */
    private static boolean samePoint(RouteLegResponse leg) {
        return Math.abs(leg.fromLat() - leg.toLat()) < 1e-7
                && Math.abs(leg.fromLng() - leg.toLng()) < 1e-7;
    }

    /**
     * 연속 BIKE leg 묶음을 전체 구간(첫 leg 출발→마지막 leg 도착) 1회 조회로 처리한다
     * (S15P21A104-153). 조회 결과 좌표열을 이어붙인 뒤, 각 leg의 실제 도착 좌표에 가장 가까운
     * 지점을 경계로 잘라 나눈다 — 인접 leg가 같은 지점(좌표열의 같은 인덱스)을 공유하므로
     * 끊김이 생기지 않는다. 좌표열이 실제 도착점과 너무 동떨어져 순서를 신뢰할 수 없으면
     * (경계가 뒤로 가지 않으면) 원본을 그대로 두고 값을 지어내지 않는다.
     */
    private List<RouteLegResponse> withBikeRunGeometry(List<RouteLegResponse> run) {
        RouteLegResponse first = run.get(0);
        RouteLegResponse last = run.get(run.size() - 1);
        if (first.fromLat() == null || first.fromLng() == null
                || last.toLat() == null || last.toLng() == null) {
            return run;
        }
        Optional<MultiLineStringResponse> geometry = bikeLookup.find(
                first.fromNodeId(), last.toNodeId(),
                first.fromLat(), first.fromLng(), last.toLat(), last.toLng());
        if (geometry.isEmpty()) {
            return run;
        }
        List<List<Double>> points = flatten(geometry.get());
        if (points.size() < run.size() + 1) {
            return run;
        }
        List<RouteLegResponse> result = new ArrayList<>();
        int cursor = 0;
        for (int k = 0; k < run.size(); k++) {
            RouteLegResponse leg = run.get(k);
            int endIdx = k == run.size() - 1
                    ? points.size() - 1
                    : nearestIndex(points, cursor, leg.toLat(), leg.toLng());
            if (endIdx <= cursor) {
                return run;
            }
            MultiLineStringResponse legGeometry =
                    MultiLineStringResponse.of(List.of(new ArrayList<>(points.subList(cursor, endIdx + 1))));
            result.add(withGeometry(leg, legGeometry));
            cursor = endIdx;
        }
        return result;
    }

    private RouteLegResponse withGeometry(RouteLegResponse leg, MultiLineStringResponse geometry) {
        double distance = distanceOf(geometry);
        double minutes = leg.minutes();
        if (leg.mode() == TravelMode.WALK && distance > 0) {
            // 표시 시간 정정(임시방편): FE가 그리는 실제 경로(카카오 폴리라인) 길이 기준.
            // 탐색 비용(직선)은 그대로라 선정·순위는 바뀌지 않는다 — 탐색 왜곡은 P2/P3 과제.
            // geometry 없으면 엔진 값을 유지한다(위 withGeometry(leg) 분기).
            minutes = distance / WalkEdgeBuilder.METERS_PER_SEC / 60.0;
        }
        return new RouteLegResponse(
                leg.mode(),
                leg.fromNodeId(), leg.fromNodeName(), leg.fromLat(), leg.fromLng(),
                leg.toNodeId(), leg.toNodeName(), leg.toLat(), leg.toLng(),
                leg.routeId(), minutes, leg.waitMinutes(),
                geometry, "available",
                distance, leg.routeName(), leg.routeOptions(),
                leg.congestionGrade(), leg.transitionType(), leg.fromRentalId(), leg.toRentalId(),
                leg.congestionLevel()
        );
    }

    /** MultiLineString의 모든 LineString 좌표를 순서대로 이어붙인다. */
    private static List<List<Double>> flatten(MultiLineStringResponse geometry) {
        List<List<Double>> points = new ArrayList<>();
        for (List<List<Double>> line : geometry.coordinates()) {
            points.addAll(line);
        }
        return points;
    }

    /** {@code fromIdx} 이후 지점 중 목표 좌표에 가장 가까운 인덱스. 역행하지 않도록 이후 구간만 본다. */
    private static int nearestIndex(List<List<Double>> points, int fromIdx, double targetLat, double targetLng) {
        int best = fromIdx;
        double bestDist = Double.MAX_VALUE;
        for (int idx = fromIdx; idx < points.size(); idx++) {
            List<Double> point = points.get(idx);
            double dist = GeoDistance.haversineMeters(point.get(1), point.get(0), targetLat, targetLng);
            if (dist < bestDist) {
                bestDist = dist;
                best = idx;
            }
        }
        return best;
    }

    /**
     * geometry 좌표를 따라 실제 이동 거리를 더한다(FE-175 항목8). geometry가 없으면(직선거리로
     * 대체하지 않고) 호출하지 않는다 — {@link #withGeometry(RouteLegResponse)}에서만 쓴다.
     */
    private static double distanceOf(MultiLineStringResponse geometry) {
        double total = 0;
        for (List<List<Double>> line : geometry.coordinates()) {
            for (int i = 0; i + 1 < line.size(); i++) {
                List<Double> from = line.get(i);
                List<Double> to = line.get(i + 1);
                total += GeoDistance.haversineMeters(from.get(1), from.get(0), to.get(1), to.get(0));
            }
        }
        return total;
    }

    /** legs 전부가 distanceMeters를 확보한 경우에만 합을 낸다. 하나라도 없으면 null(FE-175 항목8). */
    private static Double totalDistanceOf(List<RouteLegResponse> legs) {
        double sum = 0;
        for (RouteLegResponse leg : legs) {
            if (leg.distanceMeters() == null) {
                return null;
            }
            sum += leg.distanceMeters();
        }
        return sum;
    }
}
