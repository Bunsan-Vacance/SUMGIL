package com.ssafy.s15p21a104.load;

import com.ssafy.s15p21a104.load.bike.BikeStationRow;
import com.ssafy.s15p21a104.load.bikepred.BikeStockPredRow;
import com.ssafy.s15p21a104.load.bus.BusRouteRow;
import com.ssafy.s15p21a104.load.bus.BusStopRow;
import com.ssafy.s15p21a104.load.crowd.CongestionRow;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
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
    /** V2 에서 넓힌 source 열 폭. */
    static final int SOURCE_MAX = 16;
    /** V5 prediction_source 열 폭. 실제 값 중 가장 긴 것이 station_global_fallback 23자라 여유가 크지 않다. */
    static final int PREDICTION_SOURCE_MAX = 32;
    /** 적재 대여소가 마스터에 없을 때 경고에 담는 예시 수. */
    private static final int EXAMPLE_LIMIT = 10;

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

    /**
     * bike_stock_pred 적재 전 검증. 기본키 중복·범위·값 규약은 오류로 막는다.
     * <p>
     * <b>마스터에 없는 대여소는 오류가 아니라 경고다.</b> 혼잡도는 적재되지 않은 역을 오류로 막지만 여기서는 그럴 수 없다 —
     * 예측 표가 대여소 마스터보다 최근이라 신설 대여소가 정상적으로 섞이고(2026-09-17 산출물에 96곳),
     * 막으면 그 대여소의 예측을 통째로 버리게 된다. 마스터를 갱신해야 한다는 신호로만 남긴다.
     *
     * @param knownRentalIds 적재된 대여소 ID. <b>비어 있으면 대조를 건너뛴다</b> — dry-run 은 DB 를 읽지 않아 빈 집합이 온다
     */
    public static ValidationReport validateBikeStockPred(List<BikeStockPredRow> rows, Set<String> knownRentalIds) {
        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        Set<String> keys = new HashSet<>();
        Set<String> unknownRentalIds = new LinkedHashSet<>();

        for (BikeStockPredRow r : rows) {
            String label = r.rentalId() + " " + r.dowType() + "/" + r.timeSlot();
            if (!keys.add(r.rentalId() + "|" + r.dowType() + "|" + r.timeSlot())) {
                errors.add("같은 (대여소, 요일, 슬롯) 이 두 번: " + label);
                continue;
            }
            if (r.dowType() < 0 || r.dowType() > MAX_DOW_TYPE) {
                errors.add("요일 유형이 0~" + MAX_DOW_TYPE + " 밖: " + label);
            }
            if (r.timeSlot() < 0 || r.timeSlot() > MAX_TIME_SLOT) {
                errors.add("시간 슬롯이 0~" + MAX_TIME_SLOT + " 밖: " + label);
            }
            if (r.expBikes() == null || r.expBikes().signum() < 0) {
                errors.add("예상 대수가 음수이거나 없음: " + label + " (" + r.expBikes() + ")");
            }
            checkProbability("0대 확률", label, r.pEmpty(), errors);
            checkProbability("만차 확률", label, r.pFull(), errors);
            checkName("source", label, r.source(), SOURCE_MAX, errors);
            if (r.predictionSource() != null && r.predictionSource().length() > PREDICTION_SOURCE_MAX) {
                errors.add("prediction_source " + PREDICTION_SOURCE_MAX + "자 초과: " + label
                        + " (" + r.predictionSource().length() + "자)");
            }
            if (!knownRentalIds.isEmpty() && !knownRentalIds.contains(r.rentalId())) {
                unknownRentalIds.add(r.rentalId());
            }
        }

        if (!unknownRentalIds.isEmpty()) {
            warnings.add("대여소 마스터에 없는 대여소 " + unknownRentalIds.size()
                    + "곳의 예측을 함께 적재한다 (예측 표가 더 최근이다 — 마스터 갱신 필요): "
                    + head(unknownRentalIds.stream().toList()));
        }
        return new ValidationReport(errors, warnings);
    }

    /** 확률은 0~1 이다. 범위를 벗어나면 원천 단위가 % 로 바뀐 것이라 그대로 적재하면 안 된다. */
    private static void checkProbability(String label, String key, BigDecimal value, List<String> errors) {
        if (value == null) {
            errors.add(label + " 없음: " + key);
        } else if (value.signum() < 0 || value.compareTo(BigDecimal.ONE) > 0) {
            errors.add(label + " 가 0~1 밖: " + key + " (" + value + ")");
        }
    }

    private static String head(List<String> items) {
        String joined = String.join(", ", items.subList(0, Math.min(EXAMPLE_LIMIT, items.size())));
        return items.size() > EXAMPLE_LIMIT ? joined + ", …(" + items.size() + ")" : joined;
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
