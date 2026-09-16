package com.ssafy.s15p21a104.load.subway;

import java.util.List;
import java.util.Map;

/**
 * 적재 직전의 지하철 정적 데이터 묶음. 검증을 통과한 뒤에만 DB 에 쓴다.
 *
 * @param slotWaits 엣지 키("from|to|route", station_id 기준) → 요일×슬롯 기대 대기. 시각표가 없는 엣지(코레일 avg)는 키가 없고 wait_sec 0 이 된다
 */
public record SubwayGraph(List<LineRow> lines, List<StationRow> stations,
                          List<TransferMetaRow> transfers, List<EdgeRow> edges,
                          Map<String, SlotWaits> slotWaits) {

    public SubwayGraph(List<LineRow> lines, List<StationRow> stations, List<TransferMetaRow> transfers, List<EdgeRow> edges) {
        this(lines, stations, transfers, edges, Map.of());
    }
}
