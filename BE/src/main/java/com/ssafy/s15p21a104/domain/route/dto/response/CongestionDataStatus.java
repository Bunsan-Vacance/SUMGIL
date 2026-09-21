package com.ssafy.s15p21a104.domain.route.dto.response;

/** 혼잡 데이터 제공 상태 — 기술 enum을 사용자 문구로 노출하지 않는다 (FE-BE 통합 계약 §2). */
public enum CongestionDataStatus {
    AVAILABLE,
    LINE1_TRUNCATED,
    NO_CALIBRATION,
    NO_LOOKUP
}
