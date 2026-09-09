package com.ssafy.s15p21a104.load;

import com.ssafy.s15p21a104.load.bike.BikeStationRow;
import com.ssafy.s15p21a104.load.bus.BusRouteRow;
import com.ssafy.s15p21a104.load.bus.BusStopRow;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 마스터 3종(bus_stop · bus_route · bike_station)의 스키마가 강제하지 않는 규칙을 적재 전에 검증한다.
 * 오류가 하나라도 있으면 적재하지 않는다. 원천에 없는 값(좌표·거치대수 null)은 채우지 않고 경고 또는 통과다.
 * 길이 한도는 V1 DDL 과 같다: 정류소명·대여소명 VARCHAR(100), 노선명 VARCHAR(50).
 */
public final class MasterValidator {

    static final int NAME_MAX = 100;
    static final int ROUTE_NAME_MAX = 50;

    private MasterValidator() {
    }

    public static ValidationReport validateBus(List<BusStopRow> stops, List<BusRouteRow> routes) {
        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        Set<String> stopIds = new HashSet<>();
        for (BusStopRow s : stops) {
            checkKey("stop_id", s.stopId(), s.name(), stopIds, errors);
            checkName("정류소명", s.stopId(), s.name(), NAME_MAX, errors);
            checkCoords(s.stopId(), s.name(), s.lat(), s.lng(), errors, warnings);
        }
        Set<String> routeIds = new HashSet<>();
        for (BusRouteRow r : routes) {
            checkKey("route_id", r.routeId(), r.name(), routeIds, errors);
            checkName("노선명", r.routeId(), r.name(), ROUTE_NAME_MAX, errors);
        }
        return new ValidationReport(errors, warnings);
    }

    public static ValidationReport validateBike(List<BikeStationRow> stations) {
        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        Set<String> ids = new HashSet<>();
        for (BikeStationRow b : stations) {
            checkKey("rental_id", b.rentalId(), b.name(), ids, errors);
            checkName("대여소명", b.rentalId(), b.name(), NAME_MAX, errors);
            checkCoords(b.rentalId(), b.name(), b.lat(), b.lng(), errors, warnings);
            if (b.dockCount() != null && b.dockCount() < 0) {
                errors.add("거치대수가 음수: " + b.rentalId() + " " + b.name() + " (" + b.dockCount() + ")");
            }
        }
        return new ValidationReport(errors, warnings);
    }

    private static void checkKey(String column, String key, String name, Set<String> seen, List<String> errors) {
        if (key == null || key.isBlank()) {
            errors.add(column + " 없음: '" + name + "'");
        } else if (!seen.add(key)) {
            errors.add(column + " 중복: " + key);
        }
    }

    private static void checkName(String label, String key, String name, int max, List<String> errors) {
        if (name == null || name.isBlank()) {
            errors.add(label + " 없음: " + key);
        } else if (name.length() > max) {
            errors.add(label + " " + max + "자 초과: " + key + " (" + name.length() + "자)");
        }
    }

    private static void checkCoords(String key, String name, Double lat, Double lng, List<String> errors, List<String> warnings) {
        if (lat == null || lng == null) {
            warnings.add("좌표 없음: " + key + " " + name);
        } else if (!Coords.inMetroArea(lat, lng)) {
            errors.add("좌표가 수도권 범위 밖: " + key + " " + name + " (" + lat + ", " + lng + ")");
        }
    }
}
