package com.ssafy.s15p21a104.load;

import com.ssafy.s15p21a104.load.bike.BikeStationRow;
import com.ssafy.s15p21a104.load.bus.BusRouteRow;
import com.ssafy.s15p21a104.load.bus.BusStopRow;
import com.ssafy.s15p21a104.load.crowd.CongestionRow;
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
    /** congestion.target_type 에 쓰는 값. ROUTE 는 경로 개념이라 의미가 정해지지 않아 적재하지 않는다. */
    static final Set<String> CONGESTION_TARGETS = Set.of("STATION", "LINE");
    static final int MAX_DOW_TYPE = 2;
    static final int MAX_TIME_SLOT = 47;

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

    /**
     * 혼잡도 행. {@code target_id} 가 실제로 적재된 역·노선인지 본다 — 유령 대상이 생기면 조회가 조용히 빈 결과를 준다.
     * {@code level} 은 정원 대비 %라 <b>100 을 넘어도 정상</b>이고(원천 최대 144.6) 음수만 오류다.
     *
     * @param stationIds 적재된 station_id (STATION 타깃 검사용)
     * @param lineIds    적재된 line_id (LINE 타깃 검사용)
     */
    public static ValidationReport validateCongestion(List<CongestionRow> rows, Set<String> stationIds, Set<String> lineIds) {
        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        Set<String> keys = new HashSet<>();
        for (CongestionRow r : rows) {
            String label = r.targetType() + " " + r.targetId() + " " + r.dowType() + "/" + r.timeSlot();
            if (!CONGESTION_TARGETS.contains(r.targetType())) {
                errors.add("모르는 target_type: " + label + " (가능: " + CONGESTION_TARGETS + ")");
                continue;
            }
            if (!keys.add(r.targetType() + "|" + r.targetId() + "|" + r.dowType() + "|" + r.timeSlot())) {
                errors.add("같은 (타깃, 요일, 슬롯) 이 두 번: " + label);
                continue;
            }
            Set<String> known = r.targetType().equals("STATION") ? stationIds : lineIds;
            if (!known.contains(r.targetId())) {
                errors.add("적재되지 않은 대상을 target_id 로 사용: " + label);
            }
            if (r.dowType() < 0 || r.dowType() > MAX_DOW_TYPE) {
                errors.add("요일 유형이 0~" + MAX_DOW_TYPE + " 밖: " + label);
            }
            if (r.timeSlot() < 0 || r.timeSlot() > MAX_TIME_SLOT) {
                errors.add("시간 슬롯이 0~" + MAX_TIME_SLOT + " 밖: " + label);
            }
            if (r.level() == null || r.level().signum() < 0) {
                errors.add("혼잡도가 음수이거나 없음: " + label + " (" + r.level() + ")");
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
