package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 구간·환승·좌표를 합쳐 적재용 그래프를 만든다.
 * station_id 는 정규화 역명이다 (물리 역 1행). 동명이역은 (역명|노선) 예외 표로 별도 ID 를 받는다.
 * 좌표는 소속 노선의 좌표를 우선 쓰고, 없으면 같은 이름의 다른 노선 좌표, 그것도 없으면 null 이다.
 */
public final class SubwayGraphBuilder {

    private final Map<String, String> disambiguation;

    /** @param disambiguation "역명|lineId" → station_id. 예: "신촌|1063" → "신촌_경의중앙" */
    public SubwayGraphBuilder(Map<String, String> disambiguation) {
        this.disambiguation = Map.copyOf(disambiguation);
    }

    public SubwayGraph build(List<Segment> segments, List<TransferRecord> transfers, List<StationCoord> coords) {
        Map<String, StationAcc> stations = new LinkedHashMap<>();
        Set<String> lineIds = new LinkedHashSet<>();

        for (Segment s : segments) {
            lineIds.add(s.lineId());
            accumulate(stations, s.fromName(), s.lineId());
            accumulate(stations, s.toName(), s.lineId());
        }
        for (TransferRecord t : transfers) {
            lineIds.add(t.fromLineId());
            lineIds.add(t.toLineId());
        }

        Map<String, StationCoord> byLineAndName = new LinkedHashMap<>();
        Map<String, StationCoord> byName = new LinkedHashMap<>();
        for (StationCoord c : coords) {
            byLineAndName.putIfAbsent(c.lineId() + "|" + c.stationName(), c);
            byName.putIfAbsent(c.stationName(), c);
        }

        List<StationRow> stationRows = new ArrayList<>();
        for (StationAcc acc : stations.values()) {
            StationCoord coord = null;
            for (String lineId : acc.lineIds) {
                coord = byLineAndName.get(lineId + "|" + acc.name);
                if (coord != null) {
                    break;
                }
            }
            if (coord == null) {
                coord = byName.get(acc.name);
            }
            stationRows.add(new StationRow(acc.stationId, acc.name,
                    coord == null ? null : coord.lat(), coord == null ? null : coord.lng(),
                    Set.copyOf(acc.lineIds)));
        }

        List<LineRow> lineRows = lineIds.stream().map(id -> new LineRow(id, LineCodes.nameOf(id))).toList();

        List<TransferMetaRow> transferRows = transfers.stream()
                .map(t -> new TransferMetaRow(stationId(t.stationName(), t.fromLineId()),
                        t.fromLineId(), t.toLineId(), t.walkSec(), "extract"))
                .toList();

        Map<String, EdgeRow> edges = new LinkedHashMap<>();
        for (Segment s : segments) {
            String from = stationId(s.fromName(), s.lineId());
            String to = stationId(s.toName(), s.lineId());
            EdgeRow forward = new EdgeRow(from, to, "SUBWAY", s.lineId(), s.travelSec(), s.source());
            EdgeRow backward = new EdgeRow(to, from, "SUBWAY", s.lineId(), s.travelSec(), s.source());
            edges.putIfAbsent(edgeKey(forward), forward);
            edges.putIfAbsent(edgeKey(backward), backward);
        }

        return new SubwayGraph(lineRows, stationRows, transferRows, new ArrayList<>(edges.values()));
    }

    private void accumulate(Map<String, StationAcc> stations, String name, String lineId) {
        String id = stationId(name, lineId);
        stations.computeIfAbsent(id, k -> new StationAcc(id, name)).lineIds.add(lineId);
    }

    private String stationId(String name, String lineId) {
        return disambiguation.getOrDefault(name + "|" + lineId, name);
    }

    private static String edgeKey(EdgeRow e) {
        return e.fromNode() + "|" + e.toNode() + "|" + e.routeId();
    }

    private static final class StationAcc {
        final String stationId;
        final String name;
        final Set<String> lineIds = new LinkedHashSet<>();

        StationAcc(String stationId, String name) {
            this.stationId = stationId;
            this.name = name;
        }
    }
}
