package com.ssafy.s15p21a104.domain.buscongestion;

import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;

/**
 * 버스 도착정보 응답(공공데이터포털 15000314 {@code getLowArrInfoByStId}) → 노선별 혼잡 등급
 * (S15P21A104-297).
 *
 * <p>응답 모양은 {@code msgHeader.headerCd} + {@code msgBody.itemList} 다. 행 하나가 그 정류소에
 * 서는 노선 하나이고, 등급은 {@code reride_Num1}, 도착까지 남은 초는 {@code traTime1} 이다.
 *
 * <p><b>거르는 기준은 등급 코드 하나다.</b> 운행종료·출발대기·회차대기 같은 {@code arrmsg1} 문구로
 * 거르지 않는다 — 문구는 종류가 열려 있어 깨지기 쉽고, 실측에서 그런 행은 전부 코드 0 이었다.
 * 경기·인천 버스도 서울시 API 라 값이 없어 코드 0 으로 온다. 결국 <b>쓸 수 있는 값이 있는 행만
 * 남는다</b>({@link BusCongestionGrade#ofCode}).
 */
public final class BusCongestionParser {

    /** {@code msgHeader.headerCd} 정상값. */
    private static final String OK = "0";

    private static final String SOURCE = "bus.arrival";

    private static final TypeReference<Map<String, Object>> MAP = new TypeReference<>() {
    };

    private BusCongestionParser() {
    }

    /**
     * @param mapper JSON 매퍼
     * @param body   응답 본문
     * @return 노선 ID → 다음 도착 버스. 등급을 읽을 수 있는 행이 없으면 빈 맵(예외 아님)
     * @throws SourceCallException 본문이 JSON 이 아니거나({@code PARSE})
     *                             {@code headerCd} 가 정상이 아닐 때({@code API_ERROR})
     */
    public static Map<String, BusArrival> parse(JsonMapper mapper, String body) {
        Map<String, Object> root = readObject(mapper, body);
        requireOkHeader(root);

        Map<String, BusArrival> out = new LinkedHashMap<>();
        for (Map<String, Object> row : rows(at(root, "msgBody", "itemList"))) {
            toArrival(row).ifPresent(arrival ->
                    out.merge(arrival.routeId(), arrival, BusArrival::soonerOf));
        }
        return out;
    }

    private static java.util.Optional<BusArrival> toArrival(Map<String, Object> row) {
        String routeId = text(row.get("busRouteId"));
        if (routeId == null || routeId.isBlank()) {
            return java.util.Optional.empty();
        }
        Integer code = intOrNull(row.get("reride_Num1"));
        if (code == null) {
            return java.util.Optional.empty();
        }
        Integer arrivalSec = intOrNull(row.get("traTime1"));
        return BusCongestionGrade.ofCode(code)
                .map(grade -> new BusArrival(routeId.trim(), grade, arrivalSec == null ? 0 : arrivalSec));
    }

    private static Map<String, Object> readObject(JsonMapper mapper, String body) {
        try {
            Map<String, Object> parsed = mapper.readValue(body, MAP);
            if (parsed == null) {
                throw SourceCallException.parse(SOURCE, new IllegalStateException("본문이 비어 있다"));
            }
            return parsed;
        } catch (JacksonException e) {
            throw SourceCallException.parse(SOURCE, e);
        }
    }

    private static void requireOkHeader(Map<String, Object> root) {
        Object header = root.get("msgHeader");
        if (!(header instanceof Map<?, ?> map)) {
            return; // 헤더가 없는 응답 모양도 있어 본문 유무로 판단한다
        }
        String code = text(map.get("headerCd"));
        if (code != null && !OK.equals(code.trim())) {
            throw SourceCallException.apiError(SOURCE, code.trim(), text(map.get("headerMsg")));
        }
    }

    /** 중첩 맵을 키 순서대로 내려간다. 도중에 없거나 맵이 아니면 null. */
    private static Object at(Object root, String... keys) {
        Object cur = root;
        for (String key : keys) {
            if (!(cur instanceof Map<?, ?> map)) {
                return null;
            }
            cur = map.get(key);
        }
        return cur;
    }

    /** 행 목록. 1건이면 배열이 아니라 객체 하나로 오는 API 라 둘 다 받는다. */
    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rows(Object value) {
        List<Map<String, Object>> out = new java.util.ArrayList<>();
        if (value instanceof List<?> list) {
            for (Object item : list) {
                if (item instanceof Map<?, ?> map) {
                    out.add((Map<String, Object>) map);
                }
            }
        } else if (value instanceof Map<?, ?> map) {
            out.add((Map<String, Object>) map);
        }
        return out;
    }

    private static String text(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    /** 원천이 숫자를 문자열로도 준다. 숫자로 못 읽으면 null — 추측하지 않는다. */
    private static Integer intOrNull(Object value) {
        if (value instanceof Number n) {
            return n.intValue();
        }
        if (value instanceof String s && !s.isBlank()) {
            try {
                return Integer.valueOf(s.trim());
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }
}
