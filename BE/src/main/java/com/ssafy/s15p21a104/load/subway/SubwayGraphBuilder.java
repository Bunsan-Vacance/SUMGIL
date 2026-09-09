package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 구간·환승·좌표를 합쳐 적재용 그래프를 만든다.
 * station_id 는 StationIdTable(conf/station-ids.csv)이 정한다 — 서울교통공사 역번호, 물리 역 1행. 역명은 표시용 name 으로만 남는다.
 * 표에 없는 역이 나오면 build 가 IllegalStateException 으로 멈춘다 (유령 ID 방지).
 * 좌표는 소속 노선의 좌표를 우선 쓰고, 없으면 같은 이름의 다른 노선 좌표, 그것도 없으면 null 이다.
 * 시각표에서 온 방향 있는 구간({@link DirectedSegment})은 그 방향 엣지 하나만, 거리 기반 무방향 구간({@link Segment})은 양방향 엣지를 만든다.
 */
public final class SubwayGraphBuilder {

    private final StationIdTable ids;
    private final Set<String> unknown = new LinkedHashSet<>();

    /** @param ids (정규화 역명, 노선) → station_id 표. 테스트에서는 {@link StationIdTable#identity()} */
    public SubwayGraphBuilder(StationIdTable ids) {
        this.ids = ids;
    }

    public SubwayGraph build(List<Segment> segments, List<TransferRecord> transfers, List<StationCoord> coords) {
        return build(List.of(), segments, transfers, coords, Map.of());
    }

    /**
     * @param directed    시각표 구간 (방향 있음, 역방향을 만들지 않음)
     * @param undirected  거리 기반 구간 (양방향 엣지)
     * @param waitsByName "lineId|출발역명|도착역명" → 슬롯별 대기. station_id 기준 엣지 키("from|to|route")로 바꿔 그래프에 싣는다
     */
    public SubwayGraph build(List<DirectedSegment> directed, List<Segment> undirected, List<TransferRecord> transfers,
                             List<StationCoord> coords, Map<String, SlotWaits> waitsByName) {
        unknown.clear();
        Map<String, StationAcc> stations = new LinkedHashMap<>();
        Set<String> lineIds = new LinkedHashSet<>();
        for (DirectedSegment s : directed) {
            lineIds.add(s.lineId());
            accumulate(stations, s.fromName(), s.lineId());
            accumulate(stations, s.toName(), s.lineId());
        }
        for (Segment s : undirected) {
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
        for (DirectedSegment s : directed) {
            EdgeRow forward = new EdgeRow(stationId(s.fromName(), s.lineId()), stationId(s.toName(), s.lineId()),
                    "SUBWAY", s.lineId(), s.travelSec(), s.source());
            edges.putIfAbsent(EdgeTimeExpander.edgeKey(forward), forward);
        }
        for (Segment s : undirected) {
            String from = stationId(s.fromName(), s.lineId());
            String to = stationId(s.toName(), s.lineId());
            EdgeRow forward = new EdgeRow(from, to, "SUBWAY", s.lineId(), s.travelSec(), s.source());
            EdgeRow backward = new EdgeRow(to, from, "SUBWAY", s.lineId(), s.travelSec(), s.source());
            edges.putIfAbsent(EdgeTimeExpander.edgeKey(forward), forward);
            edges.putIfAbsent(EdgeTimeExpander.edgeKey(backward), backward);
        }

        Map<String, SlotWaits> slotWaits = new LinkedHashMap<>();
        for (Map.Entry<String, SlotWaits> e : waitsByName.entrySet()) {
            String[] k = e.getKey().split("\\|", 3);
            slotWaits.put(stationId(k[1], k[0]) + "|" + stationId(k[2], k[0]) + "|" + k[0], e.getValue());
        }
        if (!unknown.isEmpty()) {
            throw new IllegalStateException("역 ID 표(conf/station-ids.csv)에 없는 역 " + unknown.size() + "개 — 행을 추가한 뒤 다시 적재: "
                    + String.join(", ", unknown));
        }
        return new SubwayGraph(lineRows, stationRows, transferRows, new ArrayList<>(edges.values()), slotWaits);
    }

    private void accumulate(Map<String, StationAcc> stations, String name, String lineId) {
        String id = stationId(name, lineId);
        stations.computeIfAbsent(id, k -> new StationAcc(id, name)).lineIds.add(lineId);
    }

    private String stationId(String name, String lineId) {
        return ids.idOf(name, lineId).orElseGet(() -> {
            unknown.add(name + " (" + lineId + ")");
            return name;
        });
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
