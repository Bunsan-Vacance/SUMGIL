package com.ssafy.s15p21a104.domain.ops.dto.response;

import java.util.List;

/** 호선 1개의 슬롯 10~47 셀 목록(38칸, 슬롯 오름차순). */
public record HeatmapLine(String lineId, String lineName, List<HeatmapCell> cells) {
}
