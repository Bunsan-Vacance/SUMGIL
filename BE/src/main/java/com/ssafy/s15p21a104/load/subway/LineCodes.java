package com.ssafy.s15p21a104.load.subway;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * line_id 정본은 서울시 실시간 지하철 API 의 subwayId(4자리)다.
 * 수집기가 도착 이벤트의 subwayId 를 변환 없이 route_id 로 쓰기 위해서다.
 * 모르는 표기는 Optional.empty() 로 돌려주고 호출자가 경고로 보고한다 — 추측으로 채우지 않는다.
 */
public final class LineCodes {

    private static final Map<String, String> NAMES = new LinkedHashMap<>();
    private static final Map<String, String> BY_NAME = new LinkedHashMap<>();
    private static final Map<String, String> BY_KORAIL_CODE = new LinkedHashMap<>();

    static {
        for (int i = 1; i <= 9; i++) {
            NAMES.put("100" + i, i + "호선");
        }
        NAMES.put("1063", "경의중앙선");
        NAMES.put("1065", "공항철도");
        NAMES.put("1067", "경춘선");
        NAMES.put("1075", "수인분당선");
        NAMES.put("1077", "신분당선");
        NAMES.put("1081", "경강선");
        NAMES.put("1092", "우이신설선");
        NAMES.put("1093", "서해선");
        NAMES.put("1094", "신림선");
        NAMES.forEach((id, name) -> BY_NAME.put(name, id));

        // 환승·구간 파일에 등장하는 다른 표기
        BY_NAME.put("국철", "1001");
        BY_NAME.put("경원선", "1001");
        BY_NAME.put("경부선", "1001");
        BY_NAME.put("경인선", "1001");
        BY_NAME.put("경의선", "1063");
        BY_NAME.put("중앙선", "1063");
        BY_NAME.put("분당선", "1075");
        BY_NAME.put("수인선", "1075");
        BY_NAME.put("인천국제공항철도", "1065");

        // 공공데이터포털 "도시철도 구간정보"(코레일 광역 구간)의 노선 코드
        BY_KORAIL_CODE.put("4", "1004");     // 4호선 경계 구간 (남태령–선바위)
        BY_KORAIL_CODE.put("101", "1001");   // 경부선
        BY_KORAIL_CODE.put("102", "1001");   // 경인선
        BY_KORAIL_CODE.put("108", "1001");   // 경원선
        BY_KORAIL_CODE.put("109", "1001");   // 장항선 (천안 이남, 권역 밖)
        BY_KORAIL_CODE.put("103", "1063");   // 경의중앙선
        BY_KORAIL_CODE.put("110", "1063");   // 경의선 용산 구간
        BY_KORAIL_CODE.put("104", "1004");   // 안산선
        BY_KORAIL_CODE.put("105", "1004");   // 과천선
        BY_KORAIL_CODE.put("106", "1075");   // 분당선
    }

    private LineCodes() {
    }

    /** 서울교통공사 파일의 "호선" 값(1~9). */
    public static Optional<String> fromSeoulMetroLine(String lineNumber) {
        if (lineNumber == null) {
            return Optional.empty();
        }
        String n = lineNumber.trim();
        if (n.length() == 1 && n.charAt(0) >= '1' && n.charAt(0) <= '9') {
            return Optional.of("100" + n);
        }
        return Optional.empty();
    }

    /** "4호선", "경의중앙선", "국철" 같은 이름 표기. */
    public static Optional<String> fromName(String name) {
        if (name == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(BY_NAME.get(name.trim()));
    }

    /** 코레일 구간 파일의 노선 코드. */
    public static Optional<String> fromKorailCode(String code) {
        if (code == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(BY_KORAIL_CODE.get(code.trim()));
    }

    /** 표시 이름. 모르는 ID 는 ID 그대로. */
    public static String nameOf(String lineId) {
        return NAMES.getOrDefault(lineId, lineId);
    }

    /**
     * KTDB 철도망(RAILLINEN3) 표기. "서울"/"서울지하철" 접두어와 괄호 설명을 뗀 뒤
     * {@link #fromName(String)}으로 조회한다.
     * 예: "서울2호선"→"2호선", "서울지하철9호선"→"9호선", "경춘선(수도권전철)"→"경춘선".
     * 수도권 밖 노선(부산1호선·대구1호선 등)은 접두어 자체가 달라 조회에 실패한다 —
     * 우리 노선표(line 테이블)에 없는 노선이라 의도된 동작이다.
     */
    public static Optional<String> fromKtdbServiceName(String raw) {
        if (raw == null || raw.isBlank()) {
            return Optional.empty();
        }
        String n = raw.strip();
        int paren = n.indexOf('(');
        if (paren >= 0) {
            n = n.substring(0, paren).strip();
        }
        if (n.startsWith("서울지하철")) {
            n = n.substring("서울지하철".length());
        } else if (n.startsWith("서울")) {
            n = n.substring("서울".length());
        }
        return fromName(n);
    }
}
