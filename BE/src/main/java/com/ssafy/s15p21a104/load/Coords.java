package com.ssafy.s15p21a104.load;

/**
 * 좌표 공통 규칙. 수도권 전철·버스망을 넉넉히 감싸는 범위 밖이면 위경도 열이 뒤바뀐 것 같은 파싱 오류로 본다.
 * 원천의 빈 좌표는 null 로 남긴다 — 값을 만들어 넣지 않는다 (데이터 검증 리포트 원칙 1).
 */
public final class Coords {

    public static final double LAT_MIN = 36.5;
    public static final double LAT_MAX = 38.5;
    public static final double LNG_MIN = 126.0;
    public static final double LNG_MAX = 128.0;

    private Coords() {
    }

    public static boolean inMetroArea(double lat, double lng) {
        return lat >= LAT_MIN && lat <= LAT_MAX && lng >= LNG_MIN && lng <= LNG_MAX;
    }

    /** 빈 문자열·null 은 null. 숫자가 아닌 값은 원천 결함이므로 NumberFormatException 으로 멈춘다. */
    public static Double parseOrNull(String text) {
        if (text == null) {
            return null;
        }
        String trimmed = text.trim();
        return trimmed.isEmpty() ? null : Double.valueOf(trimmed);
    }

    public static Integer parseIntOrNull(String text) {
        if (text == null) {
            return null;
        }
        String trimmed = text.trim();
        return trimmed.isEmpty() ? null : Integer.valueOf(trimmed);
    }
}
