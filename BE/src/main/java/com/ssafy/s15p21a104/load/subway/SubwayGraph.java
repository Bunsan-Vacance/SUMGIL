package com.ssafy.s15p21a104.load.subway;

import java.util.List;

/** 적재 직전의 지하철 정적 데이터 묶음. 검증을 통과한 뒤에만 DB 에 쓴다. */
public record SubwayGraph(List<LineRow> lines, List<StationRow> stations,
                          List<TransferMetaRow> transfers, List<EdgeRow> edges) {
}
