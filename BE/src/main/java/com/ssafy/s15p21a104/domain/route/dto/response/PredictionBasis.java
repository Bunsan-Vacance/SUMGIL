package com.ssafy.s15p21a104.domain.route.dto.response;

/** 혼잡 예측 근거 — D+0~D+3 서울 기준 (FE-BE 통합 계약 §2). */
public enum PredictionBasis {
    RECENT_7D,
    PARTIAL,
    WEEKDAY_AVERAGE
}
