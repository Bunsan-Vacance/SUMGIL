package com.ssafy.s15p21a104.domain.route.mapper;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

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
            long seconds
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
        if (enginePath == null || enginePath.segments() == null || enginePath.segments().isEmpty()) {
            return Optional.empty();
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

        List<RouteLegResponse> legs = splitLegs(segments, stationsById);
        if (legs.size() - 1 != enginePath.transferCount()) {
            throw new IllegalArgumentException("환승 횟수와 노선 전환 경계가 일치하지 않는다");
        }

        double totalMinutes = enginePath.totalSeconds() / 60.0;
        return Optional.of(new RouteSearchResponse(routeType, totalMinutes, List.copyOf(legs), source));
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
                legs.add(toLeg(segments.subList(start, i), stationsById));
                start = i;
            }
        }
        return legs;
    }

    /** 같은 노선 이동 묶음을 구간 응답 하나로 바꾼다. */
    private static RouteLegResponse toLeg(
            List<EngineSegment> group, Map<String, StationInfo> stationsById) {
        EngineSegment first = group.get(0);
        EngineSegment last = group.get(group.size() - 1);
        StationInfo from = requireStation(stationsById, first.fromStationId());
        StationInfo to = requireStation(stationsById, last.toStationId());
        long sum = 0;
        for (EngineSegment segment : group) {
            sum += segment.seconds();
        }
        return new RouteLegResponse(
                TravelMode.SUBWAY,
                from.stationId(), from.name(), from.lat(), from.lng(),
                to.stationId(), to.name(), to.lat(), to.lng(),
                first.routeId(),
                sum / 60.0
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
