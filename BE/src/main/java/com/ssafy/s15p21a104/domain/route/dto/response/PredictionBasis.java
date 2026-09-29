package com.ssafy.s15p21a104.domain.route.dto.response;

/** 혼잡 예측 근거 — D+0~D+3 서울 기준 (FE-BE 통합 계약 §2). */
public enum PredictionBasis {
    RECENT_7D,
    PARTIAL,
    WEEKDAY_AVERAGE,
    /** BUS 실시간 등급(297)을 공통 수치 축으로 옮긴 값(2026-09-22). */
    LIVE
}
