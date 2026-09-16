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
    private static final Map<String, String> BY_STD_CODE = new LinkedHashMap<>();

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
        BY_NAME.put("인천국제공항선", "1065");   // 표준데이터 노선명
        BY_NAME.put("공항선", "1065");
        BY_NAME.put("안산과천선", "1004");       // 코레일 물리 선로 표기 — 4호선 운행 구간
        BY_NAME.put("안산선", "1004");
        BY_NAME.put("과천선", "1004");
        BY_NAME.put("진접선", "1004");
        BY_NAME.put("일산선", "1003");

        // 전국도시철도역사정보표준데이터(15013205)의 노선번호. 서비스 노선이 하나로 정해지는 코드만 둔다 —
        // 경원선 I4102(1호선·경의중앙·경춘 공용)처럼 물리 선로 코드는 비워 두고 호출자가 이름으로만 쓴다.
        for (int i = 1; i <= 9; i++) {
            BY_STD_CODE.put("S110" + i, "100" + i);
        }
        BY_STD_CODE.put("S1121", "1002");   // 2호선 성수지선
        BY_STD_CODE.put("S1122", "1002");   // 2호선 신정지선
        BY_STD_CODE.put("I4101", "1001");   // 1호선(서울교통공사 표기)·경부선
        BY_STD_CODE.put("I1101", "1001");   // 경인선
        BY_STD_CODE.put("I1103", "1003");
        BY_STD_CODE.put("I4106", "1003");   // 일산선
        BY_STD_CODE.put("I1104", "1004");
        BY_STD_CODE.put("I4103", "1004");   // 안산과천선
        BY_STD_CODE.put("I4104", "1004");   // 진접선
        BY_STD_CODE.put("S4108", "1008");   // 8호선 별내선(남양주도시공사)
        BY_STD_CODE.put("I4108", "1063");   // 경의중앙선
        BY_STD_CODE.put("I4105", "1075");   // 분당선
        BY_STD_CODE.put("I28K1", "1075");   // 수인선
        BY_STD_CODE.put("I41K2", "1067");   // 경춘선
        BY_STD_CODE.put("I41K5", "1081");   // 경강선
        BY_STD_CODE.put("I41WS", "1093");   // 서해선
        BY_STD_CODE.put("I28A1", "1065");   // 인천국제공항선
        BY_STD_CODE.put("I11D1", "1077");   // 신분당선
        BY_STD_CODE.put("L11UI", "1092");   // 우이신설선
        BY_STD_CODE.put("L11SL", "1094");   // 신림선
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

    /**
     * 국토교통부 "도시철도 전체노선"(15122916)의 노선명. '선'이 빠진 표기("경의중앙", "경춘", "신분당")와 "공항"(공항철도)을 받는다.
     * 실시간 API 코드가 없는 노선(인천1호선·에버라인·GTX-A)은 비어 있다.
     */
    public static Optional<String> fromUrbanLineName(String name) {
        if (name == null) {
            return Optional.empty();
        }
        String n = name.trim();
        if (n.equals("공항")) {
            return Optional.of("1065");
        }
        Optional<String> id = fromName(n);
        return id.isPresent() ? id : fromName(n + "선");
    }

    /** 전국도시철도역사정보표준데이터(15013205)의 노선번호. 물리 선로 공용 코드(경원선 I4102)와 코드 없는 노선은 비어 있다. */
    public static Optional<String> fromStdLineCode(String code) {
        if (code == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(BY_STD_CODE.get(code.trim()));
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
