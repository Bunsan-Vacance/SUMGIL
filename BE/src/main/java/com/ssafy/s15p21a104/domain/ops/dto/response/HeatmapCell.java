package com.ssafy.s15p21a104.domain.ops.dto.response;

import java.math.BigDecimal;

/** 호선×슬롯 셀. 행이 없는 슬롯은 level·maxLevel이 null, nLinks·nFallback이 0이다. */
public record HeatmapCell(int timeSlot, BigDecimal level, int nLinks, int nFallback, BigDecimal maxLevel) {
}
