package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 스키마가 강제하지 않는 규칙을 적재 전에 검증한다 (BE/docs/db/schema.md "모드-노드 규칙").
 * 오류가 하나라도 있으면 적재하지 않는다. 표본이 없는 값을 채워 넣지 않는 것도 여기서 지킨다 — 좌표 없음은 경고일 뿐이다.
 */
public final class LoadValidator {

    // 수도권 전철망을 넉넉히 감싸는 범위. 밖이면 좌표 열이 뒤바뀐 것 같은 파싱 오류다.
    static final double LAT_MIN = 36.5;
    static final double LAT_MAX = 38.5;
    static final double LNG_MIN = 126.0;
    static final double LNG_MAX = 128.0;

    private LoadValidator() {
    }

    public static ValidationReport validate(SubwayGraph graph) {
        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();

        Set<String> stationIds = graph.stations().stream().map(StationRow::stationId).collect(Collectors.toSet());
        Set<String> lineIds = graph.lines().stream().map(LineRow::lineId).collect(Collectors.toSet());

        for (StationRow s : graph.stations()) {
            if (s.lat() == null || s.lng() == null) {
                warnings.add("좌표 없음: " + s.stationId());
            } else if (s.lat() < LAT_MIN || s.lat() > LAT_MAX || s.lng() < LNG_MIN || s.lng() > LNG_MAX) {
                errors.add("좌표가 수도권 범위 밖: " + s.stationId() + " (" + s.lat() + ", " + s.lng() + ")");
            }
        }

        for (EdgeRow e : graph.edges()) {
            String label = e.routeId() + " " + e.fromNode() + "→" + e.toNode();
            if (e.fromNode().equals(e.toNode())) {
                errors.add("출발과 도착이 같은 엣지: " + label);
                continue;
            }
            if (e.travelSec() <= 0) {
                errors.add("이동 초가 0 이하: " + label);
            }
            if (!stationIds.contains(e.fromNode())) {
                errors.add("존재하지 않는 출발 역: " + e.fromNode() + " (" + label + ")");
            }
            if (!stationIds.contains(e.toNode())) {
                errors.add("존재하지 않는 도착 역: " + e.toNode() + " (" + label + ")");
            }
            if (!lineIds.contains(e.routeId())) {
                errors.add("적재되지 않은 노선을 route_id 로 사용: " + label);
            }
        }

        for (TransferMetaRow t : graph.transfers()) {
            if (!stationIds.contains(t.stationId())) {
                warnings.add("환승 정보의 역이 구간에 없음: " + t.stationId() + " " + t.fromLine() + "→" + t.toLine());
            }
            if (t.walkSec() <= 0) {
                errors.add("환승 도보 초가 0 이하: " + t.stationId() + " " + t.fromLine() + "→" + t.toLine());
            }
        }

        return new ValidationReport(errors, warnings);
    }
}
