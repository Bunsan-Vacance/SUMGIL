package com.ssafy.s15p21a104.domain.buscongestion;

import java.util.Optional;

/**
 * 버스 실시간 혼잡 등급 (S15P21A104-297).
 *
 * <p>원천은 공공데이터포털 15000314 버스 도착정보 {@code getLowArrInfoByStId} 의 {@code reride_Num1}
 * 이다. 이름은 "재차인원" 이지만 <b>승객 수가 아니라 등급 코드</b>다 — 2026-09-21 실측(붐비는 정류소
 * 6곳·운행 중 57대, 평일 09:45)에서 값이 0·3·4 뿐이었고, 강남역 간선 24대 중 21대가 3이었다.
 * 승객 수라면 아침 강남역 버스가 전부 3명일 수 없다.
 *
 * <p><b>실측으로 확인된 것은 0·3·4 뿐이다.</b> 5·6 은 코드표 기준이고 아직 관측되지 않았다
 * (출근 피크 재측정 항목). 그래서 <b>모르는 코드는 해석하지 않고 버린다</b> — 등급을 지어내면
 * 붐비는 버스를 여유로 보여주는 쪽이 더 위험하다.
 *
 * <p>이름은 FE {@code SegmentCongestionGrade}(`features/route/types.ts`)와 같은 4값이다. 그대로
 * 문자열로 내보내면 FE 가 이미 가진 여유·보통·혼잡·포화 4단계 색이 그대로 맞는다.
 */
public enum BusCongestionGrade {

    /** 코드 3. FE 표시 "여유". */
    RELAXED(3),
    /** 코드 4. FE 표시 "보통". */
    NORMAL(4),
    /** 코드 5. FE 표시 "혼잡". 2026-09-21 실측 미관측. */
    CONGESTED(5),
    /** 코드 6. FE 표시 "포화". 2026-09-21 실측 미관측. */
    SATURATED(6);

    /** 원천이 "정보 없음" 으로 쓰는 값. 경기·인천 버스와 운행종료·출발대기 노선이 전부 이 값이다. */
    public static final int NO_INFO_CODE = 0;

    private final int code;

    BusCongestionGrade(int code) {
        this.code = code;
    }

    public int code() {
        return code;
    }

    /**
     * @param code 원천의 {@code reride_Num1} 값
     * @return 대응 등급. {@link #NO_INFO_CODE} 이거나 표에 없는 값이면 빈 값 — 지어내지 않는다
     */
    public static Optional<BusCongestionGrade> ofCode(int code) {
        for (BusCongestionGrade grade : values()) {
            if (grade.code == code) {
                return Optional.of(grade);
            }
        }
        return Optional.empty();
    }
}
