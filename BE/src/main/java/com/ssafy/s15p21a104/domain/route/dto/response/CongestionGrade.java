package com.ssafy.s15p21a104.domain.route.dto.response;

/** 혼잡 등급 — 서버가 50/100 경계로 정한다 (FE-BE 통합 계약 §2). */
public enum CongestionGrade {
    LOW,
    MEDIUM,
    HIGH
}
