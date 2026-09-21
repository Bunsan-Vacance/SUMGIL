package com.ssafy.s15p21a104.domain.route.mapper;

import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteOptionResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;

/**
 * 탐색 엔진 결과를 최종 응답 DTO로 변환한다.
 *
 * <p>순수 함수 모음이다. DB·Spring에 의존하지 않으므로 단위 테스트에서 가짜 엔진 결과를
 * 그대로 주입할 수 있다. 시간은 엔진의 초 단위를 최종 계약의 분 단위(Double)로 바꾼다.</p>
 */
public final class RouteMapper {

    private RouteMapper() {
    }

    /** 엔진이 내놓은 이동 한 칸: 역에서 역으로의 이동과 소요 시간(초). */
    public record EngineSegment(
            String fromStationId,
            String toStationId,
            String routeId,
            long seconds,
            TravelMode mode
    ) {
    }

    /** 엔진 탐색 결과: 이동 순서·전체 소요 시간(초)·환승 횟수. */
    public record EnginePath(
            List<EngineSegment> segments,
            long totalSeconds,
            int transferCount
    ) {
    }

    /** 역 표시 정보: 이름·좌표 조회용(94 이름 매핑과 Station 좌표를 호출자가 묶어서 전달). */
    public record StationInfo(
            String stationId,
            String name,
            Double lat,
            Double lng
    ) {
    }

    /**
     * 엔진 경로 하나를 최종 응답 하나로 바꾼다.
     *
     * @param enginePath  엔진 탐색 결과(가짜 결과 주입 가능)
     * @param stationsById 역 표시 정보(역 ID 기준)
     * @param routeType   응답에 적을 경로 유형(호출자가 정한다)
     * @param source      응답에 적을 출처(호출자가 주입한다)
     * @return 경로가 없으면 비어 있음(상위 계층에서 빈 배열 응답으로 구분)
     */
    public static Optional<RouteSearchResponse> toResponse(
            EnginePath enginePath,
            Map<String, StationInfo> stationsById,
            RouteType routeType,
            RouteSource source
    ) {
        List<EngineSegment> segments = validate(enginePath, stationsById, routeType, source);
        if (segments == null) {
            return Optional.empty();
        }

        List<RouteLegResponse> legs = splitLegs(segments, stationsById);
        if (legs.size() - 1 != enginePath.transferCount()) {
            throw new IllegalArgumentException("환승 횟수와 노선 전환 경계가 일치하지 않는다");
        }

        double totalMinutes = enginePath.totalSeconds() / 60.0;
        return Optional.of(new RouteSearchResponse(
                routeType, totalMinutes, List.copyOf(legs), source, null, enginePath.transferCount(),
                null));
    }

    /**
     * 엔진 경로 하나를 최종 응답 하나로 바꾼다. 노선 전환 경계마다 환승 도보 leg를 끼운다.
     *
     * <p>기존 {@link #toResponse}는 바꾸지 않는다. 환승 1회 경로는 legs 3개
     * (SUBWAY·TRANSFER·SUBWAY)로 나온다. TRANSFER leg의 출발·도착은 환승역 자신이다.
     *
     * @param enginePath 엔진 탐색 결과(가짜 결과 주입 가능)
     * @param stationsById 역 표시 정보(역 ID 기준)
     * @param routeType 응답에 적을 경로 유형(호출자가 정한다)
     * @param source 응답에 적을 출처(호출자가 주입한다)
     * @param transferSeconds 경계 순서대로 환승 소요 초. 크기는 환승 횟수와 같아야 한다
     * @return 경로가 없으면 비어 있음(상위 계층에서 빈 배열 응답으로 구분)
     */
    public static Optional<RouteSearchResponse> toResponseWithTransfers(
            EnginePath enginePath,
            Map<String, StationInfo> stationsById,
            RouteType routeType,
            RouteSource source,
            List<Long> transferSeconds
    ) {
        return toResponseWithTransfers(
                enginePath, stationsById, routeType, source, transferSeconds, Set.of());
    }

    /**
     * 엔진 경로 하나를 최종 응답 하나로 바꾼다. 노선 전환 경계마다 환승 도보 leg를 끼운다.
     *
     * <p>대여소 집합을 넘기면 같은 노선 구간이라도 대여소 노드에서 분할한다.
     * 자전거 본선(R1→R2→R3)이 1개 leg로 합쳐져 경유 대여소가 사라지지 않는다.
     *
     * @param enginePath 엔진 탐색 결과(가짜 결과 주입 가능)
     * @param stationsById 역 표시 정보(역 ID 기준)
     * @param routeType 응답에 적을 경로 유형(호출자가 정한다)
     * @param source 응답에 적을 출처(호출자가 주입한다)
     * @param transferSeconds 경계 순서대로 환승 소요 초. 크기는 환승 횟수와 같아야 한다
     * @param rentalIds 대여소 ID 집합. 빈 집합이면 기존 합침과 같다
     * @return 경로가 없으면 비어 있음(상위 계층에서 빈 배열 응답으로 구분)
     */
    public static Optional<RouteSearchResponse> toResponseWithTransfers(
            EnginePath enginePath,
            Map<String, StationInfo> stationsById,
            RouteType routeType,
            RouteSource source,
            List<Long> transferSeconds,
            Set<String> rentalIds
    ) {
        return toResponseWithTransfers(
                enginePath, stationsById, routeType, source, transferSeconds, rentalIds, null);
    }

    /**
     * 엔진 경로 하나를 최종 응답 하나로 바꾼다. 노선 전환 경계마다 환승 도보 leg를 끼운다.
     *
     * <p>버스 구간은 정류장 쌍별 운행 노선 교집합으로 환승을 판정한다(S15P21A104-234).
     * 같은 정류장을 지나는 108→143 연속 탑승은 환승이 아니라 1개 leg로 합친다.
     *
     * @param enginePath 엔진 탐색 결과(가짜 결과 주입 가능)
     * @param stationsById 역 표시 정보(역 ID 기준)
     * @param routeType 응답에 적을 경로 유형(호출자가 정한다)
     * @param source 응답에 적을 출처(호출자가 주입한다)
     * @param transferSeconds 경계 순서대로 환승 소요 초. 크기는 환승 횟수와 같아야 한다
     * @param rentalIds 대여소 ID 집합. 빈 집합이면 기존 합침과 같다
     * @param busRouteIndex 정류장 쌍별 버스 운행 노선. null이면 노선 ID 그대로 판정한다
     * @return 경로가 없으면 비어 있음(상위 계층에서 빈 배열 응답으로 구분)
     */
    public static Optional<RouteSearchResponse> toResponseWithTransfers(
            EnginePath enginePath,
            Map<String, StationInfo> stationsById,
            RouteType routeType,
            RouteSource source,
            List<Long> transferSeconds,
            Set<String> rentalIds,
            BusRouteIndex busRouteIndex
    ) {
        List<EngineSegment> segments = validate(enginePath, stationsById, routeType, source);
        if (segments == null) {
            return Optional.empty();
        }
        Objects.requireNonNull(transferSeconds, "transferSeconds");
        Objects.requireNonNull(rentalIds, "rentalIds");
        if (transferSeconds.size() != enginePath.transferCount()) {
            throw new IllegalArgumentException("환승 횟수와 환승 시간 개수가 일치하지 않는다");
        }
        for (Long seconds : transferSeconds) {
            if (seconds == null || seconds < 0) {
                throw new IllegalArgumentException("환승 소요 시간이 음수이다");
            }
        }

        List<RouteLegResponse> legs = new ArrayList<>();
        int boundary = 0;
        java.util.Set<String> kept = java.util.Set.of();
        // BUS 묶음의 운행 노선 교집합. BUS만 유지하고 비BUS 묶음에서는 null이다.
        List<EngineSegment> curGroup = new ArrayList<>();
        java.util.Set<String> running = null;
        EngineSegment prevSeg = null;
        java.util.Set<String> prevOpts = null;
        for (EngineSegment s : segments) {
            java.util.Set<String> opts = s.mode() == TravelMode.BUS
                    ? BusRouteIndex.optionsFor(
                            new Edge(s.fromStationId(), s.toStationId(), s.routeId(),
                                    0, 0, s.mode()), busRouteIndex)
                    : java.util.Set.of(s.routeId());
            boolean groupIsBus = !curGroup.isEmpty() && curGroup.get(0).mode() == TravelMode.BUS;
            boolean routeChanged = !curGroup.isEmpty()
                    && !Objects.equals(s.routeId(), curGroup.get(0).routeId());
            boolean rentalSplit = !routeChanged && !curGroup.isEmpty()
                    && rentalIds.contains(s.fromStationId());
            boolean busSplit = !routeChanged && !rentalSplit && groupIsBus && running != null
                    && java.util.Collections.disjoint(running, opts);
            if (!curGroup.isEmpty() && (routeChanged || rentalSplit || busSplit)) {
                legs.add(toLeg(curGroup, stationsById, running));
                if (routeChanged || busSplit) {
                    TransferRule.TransferDecision decision = TransferRule.decideLines(
                            kept, prevSeg.mode(), prevOpts, s.mode(), opts);
                    if (!decision.transfer() && prevOpts.size() == 1 && opts.size() == 1) {
                        // 집합 판정이 닿지 않는 기존 직접 경계(대중교통↔BIKE·첫 경계)는
                        // 문자열 규칙으로 그대로 본다 — 단일 노선 그래프에서 기존과 바이트 동일.
                        // 입력은 집합에서 뽑은 단일 노선을 쓴다(엔진·조립기와 동일 규칙).
                        TransferRule.TransferDecision legacy = TransferRule.decide(
                                singleOrNull(kept), prevSeg.mode(), prevOpts.iterator().next(),
                                s.mode(), opts.iterator().next());
                        if (legacy.transfer()) {
                            decision = legacy;
                        }
                    }
                    if (decision.transfer()) {
                        legs.add(transferLeg(s.fromStationId(), stationsById,
                                transferSeconds.get(boundary)));
                        boundary++;
                    }
                }
                curGroup = new ArrayList<>();
                curGroup.add(s);
                running = s.mode() == TravelMode.BUS ? opts : null;
            } else {
                curGroup.add(s);
                if (s.mode() == TravelMode.BUS) {
                    if (running == null) {
                        running = opts;
                    } else {
                        java.util.Set<String> narrowed = new java.util.HashSet<>(running);
                        narrowed.retainAll(opts);
                        running = java.util.Set.copyOf(narrowed);
                    }
                }
            }
            kept = TransferRule.keptTransitLines(kept, s.mode(), opts);
            prevSeg = s;
            prevOpts = opts;
        }
        legs.add(toLeg(curGroup, stationsById, running));
        if (boundary != enginePath.transferCount()) {
            throw new IllegalArgumentException("환승 횟수와 노선 전환 경계가 일치하지 않는다");
        }

        double totalMinutes = enginePath.totalSeconds() / 60.0;
        return Optional.of(new RouteSearchResponse(
                routeType, totalMinutes, List.copyOf(legs), source, null, enginePath.transferCount(),
                null));
    }

    /** 단일 원소 집합이면 그 원소, 아니면 null — 기존 문자열 규칙 폴백용(232). */
    private static String singleOrNull(java.util.Set<String> lines) {
        if (lines == null || lines.size() != 1) {
            return null;
        }
        return lines.iterator().next();
    }

    /** 환승역 자신의 출발·도착으로 환승 도보 leg를 만든다. */
    private static RouteLegResponse transferLeg(
            String stationId, Map<String, StationInfo> stationsById, long seconds) {
        StationInfo info = requireStation(stationsById, stationId);
        return new RouteLegResponse(
                TravelMode.TRANSFER,
                info.stationId(), info.name(), info.lat(), info.lng(),
                info.stationId(), info.name(), info.lat(), info.lng(),
                null, seconds / 60.0,
                null, "unavailable",
                null, null, null);
    }

    private static List<EngineSegment> validate(
            EnginePath enginePath,
            Map<String, StationInfo> stationsById,
            RouteType routeType,
            RouteSource source) {
        if (enginePath == null || enginePath.segments() == null || enginePath.segments().isEmpty()) {
            return null;
        }
        Objects.requireNonNull(stationsById, "stationsById");
        Objects.requireNonNull(routeType, "routeType");
        Objects.requireNonNull(source, "source");
        if (enginePath.totalSeconds() < 0) {
            throw new IllegalArgumentException("전체 소요 시간이 음수이다");
        }

        List<EngineSegment> segments = List.copyOf(enginePath.segments());
        for (EngineSegment segment : segments) {
            if (segment == null || segment.fromStationId() == null || segment.toStationId() == null) {
                throw new IllegalArgumentException("이동의 역 ID가 비어 있다");
            }
            if (segment.mode() == null) {
                throw new IllegalArgumentException("이동의 수단이 비어 있다");
            }
            if (segment.seconds() < 0) {
                throw new IllegalArgumentException("이동의 소요 시간이 음수이다");
            }
        }
        // 이동 연속성: 앞 이동의 도착역이 뒷 이동의 출발역과 같아야 한다.
        for (int i = 0; i < segments.size() - 1; i++) {
            if (!segments.get(i).toStationId().equals(segments.get(i + 1).fromStationId())) {
                throw new IllegalArgumentException("이동이 이어지지 않는다: "
                        + segments.get(i).toStationId() + " -> " + segments.get(i + 1).fromStationId());
            }
        }

        return segments;
    }

    /** 노선 전환 지점을 경계로 이동들을 묶어 구간 응답으로 바꾼다. */
    private static List<RouteLegResponse> splitLegs(
            List<EngineSegment> segments, Map<String, StationInfo> stationsById) {
        List<RouteLegResponse> legs = new ArrayList<>();
        int start = 0;
        for (int i = 1; i <= segments.size(); i++) {
            boolean boundary = i == segments.size()
                    || !Objects.equals(segments.get(i).routeId(), segments.get(start).routeId());
            if (boundary) {
                legs.add(toLeg(segments.subList(start, i), stationsById, null));
                start = i;
            }
        }
        return legs;
    }

    /**
     * 같은 노선 이동 묶음을 구간 응답 하나로 바꾼다.
     *
     * @param busOptionsOrNull BUS 묶음의 운행 노선 교집합(234). BUS leg는 이름·배차 없이
     *     ID 목록으로 그대로 싣는다(이름·배차는 {@code RouteNameResolver}가 채운다).
     *     비어 있어도 null로 바꾸지 않는다 — 전 구간 단일 노선 없음의 정직한 신호다.
     *     null·비BUS 묶음은 routeOptions null(기존 동일)
     */
    private static RouteLegResponse toLeg(
            List<EngineSegment> group, Map<String, StationInfo> stationsById,
            java.util.Set<String> busOptionsOrNull) {
        EngineSegment first = group.get(0);
        EngineSegment last = group.get(group.size() - 1);
        StationInfo from = requireStation(stationsById, first.fromStationId());
        StationInfo to = requireStation(stationsById, last.toStationId());
        long sum = 0;
        for (EngineSegment segment : group) {
            if (segment.mode() == null || segment.mode() != first.mode()) {
                throw new IllegalArgumentException("묶음 안의 수단이 다르다");
            }
            sum += segment.seconds();
        }
        List<RouteOptionResponse> routeOptions = null;
        if (first.mode() == TravelMode.BUS && busOptionsOrNull != null) {
            List<String> ids = busOptionsOrNull.stream().sorted().toList();
            routeOptions = RouteOptionResponse.of(ids, Map.of(), Map.of());
        }
        return new RouteLegResponse(
                first.mode(),
                from.stationId(), from.name(), from.lat(), from.lng(),
                to.stationId(), to.name(), to.lat(), to.lng(),
                first.routeId(),
                sum / 60.0,
                // KTDB geometry·거리·노선명은 RouteMapper가 모른다(DB 비의존 순수 함수) —
                // RouteSearchService가 후처리로 채운다. 계약 필드(236·237·297)도 후처리 몫이라
                // 16인자 호환 생성자를 쓴다.
                null, "unavailable",
                null, null, routeOptions
        );
    }

    private static StationInfo requireStation(Map<String, StationInfo> stationsById, String stationId) {
        StationInfo info = stationsById.get(stationId);
        if (info == null) {
            throw new IllegalArgumentException("역 정보를 찾을 수 없음: " + stationId);
        }
        return info;
    }
}
