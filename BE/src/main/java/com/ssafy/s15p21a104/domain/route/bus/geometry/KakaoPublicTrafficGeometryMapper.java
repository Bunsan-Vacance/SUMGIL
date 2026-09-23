package com.ssafy.s15p21a104.domain.route.bus.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.bus.geometry.KakaoPublicTrafficResponse.Path;
import com.ssafy.s15p21a104.domain.route.bus.geometry.KakaoPublicTrafficResponse.Properties;
import com.ssafy.s15p21a104.domain.route.bus.geometry.KakaoPublicTrafficResponse.Route;
import com.ssafy.s15p21a104.domain.route.bus.geometry.KakaoPublicTrafficResponse.Step;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import java.util.List;
import java.util.Optional;

/** 카카오 대중교통 응답에서 현재 BUS leg와 일치하는 도로 geometry를 찾는다. */
public final class KakaoPublicTrafficGeometryMapper {

    /** 실제 정류소와 카카오 도로 스냅점의 허용 최대 거리. */
    static final double MAX_ENDPOINT_MATCH_METERS = 100;

    private KakaoPublicTrafficGeometryMapper() {
    }

    public static Optional<MultiLineStringResponse> toMultiLineString(
            KakaoPublicTrafficResponse response,
            String routeName,
            String fromNodeName,
            String toNodeName,
            double fromLat,
            double fromLng,
            double toLat,
            double toLng) {
        if (response == null || !"OK".equals(response.status())
                || response.routes() == null || isBlank(routeName)
                || isBlank(fromNodeName) || isBlank(toNodeName)) {
            return Optional.empty();
        }
        for (Route route : response.routes()) {
            if (route == null || route.steps() == null) {
                continue;
            }
            for (Step step : route.steps()) {
                if (step == null || !matches(step.properties(), routeName, fromNodeName, toNodeName)) {
                    continue;
                }
                Optional<List<List<Double>>> points = validPoints(step.path());
                if (points.isEmpty() || !matchesEndpoints(
                        points.get(), fromLat, fromLng, toLat, toLng)) {
                    continue;
                }
                return Optional.of(MultiLineStringResponse.of(List.of(points.get())));
            }
        }
        return Optional.empty();
    }

    private static boolean matches(
            Properties properties, String routeName, String fromNodeName, String toNodeName) {
        if (properties == null || !"BUS".equalsIgnoreCase(properties.type())
                || properties.vehicles() == null || properties.stops() == null) {
            return false;
        }
        boolean routeMatches = properties.vehicles().stream()
                .filter(vehicle -> vehicle != null)
                .map(KakaoPublicTrafficResponse.Vehicle::name)
                .anyMatch(name -> sameName(name, routeName));
        if (!routeMatches) {
            return false;
        }
        int fromIndex = -1;
        for (int i = 0; i < properties.stops().size(); i++) {
            KakaoPublicTrafficResponse.Stop stop = properties.stops().get(i);
            if (stop != null && sameName(stop.name(), fromNodeName)) {
                fromIndex = i;
                break;
            }
        }
        if (fromIndex < 0) {
            return false;
        }
        for (int i = fromIndex + 1; i < properties.stops().size(); i++) {
            KakaoPublicTrafficResponse.Stop stop = properties.stops().get(i);
            if (stop != null && sameName(stop.name(), toNodeName)) {
                return true;
            }
        }
        return false;
    }

    private static Optional<List<List<Double>>> validPoints(Path path) {
        if (path == null || path.points() == null || path.points().size() < 2) {
            return Optional.empty();
        }
        for (List<Double> point : path.points()) {
            if (point == null || point.size() < 2
                    || point.get(0) == null || point.get(1) == null
                    || !Double.isFinite(point.get(0)) || !Double.isFinite(point.get(1))
                    || point.get(0) < -180 || point.get(0) > 180
                    || point.get(1) < -90 || point.get(1) > 90) {
                return Optional.empty();
            }
        }
        return Optional.of(path.points());
    }

    private static boolean matchesEndpoints(
            List<List<Double>> points,
            double fromLat,
            double fromLng,
            double toLat,
            double toLng) {
        List<Double> first = points.get(0);
        List<Double> last = points.get(points.size() - 1);
        return GeoDistance.haversineMeters(first.get(1), first.get(0), fromLat, fromLng)
                        <= MAX_ENDPOINT_MATCH_METERS
                && GeoDistance.haversineMeters(last.get(1), last.get(0), toLat, toLng)
                        <= MAX_ENDPOINT_MATCH_METERS;
    }

    private static boolean sameName(String left, String right) {
        return !isBlank(left) && !isBlank(right)
                && left.replaceAll("\\s+", "").equals(right.replaceAll("\\s+", ""));
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
