package com.ssafy.s15p21a104.load.subway;

/** 같은 역 안에서 한 노선 승강장에서 다른 노선 승강장으로 걸어가는 데 드는 초. */
public record TransferRecord(String stationName, String fromLineId, String toLineId, int walkSec) {
}
