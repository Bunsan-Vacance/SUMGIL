package com.ssafy.s15p21a104.collect.source;

import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;

/** 응답 JSON 을 맵으로 읽고 경로로 꺼내는 작은 도우미. 어댑터 셋이 같은 판정 규칙(probe 의 parseResponse)을 쓰게 한다. */
final class Json {

    private static final TypeReference<Map<String, Object>> MAP = new TypeReference<>() {
    };

    private Json() {
    }

    static Map<String, Object> object(JsonMapper mapper, String source, String body) {
        try {
            Map<String, Object> parsed = mapper.readValue(body, MAP);
            if (parsed == null) {
                throw SourceCallException.parse(source, new IllegalStateException("본문이 비어 있다"));
            }
            return parsed;
        } catch (JacksonException e) {
            throw SourceCallException.parse(source, e);
        }
    }

    /** 중첩 맵을 키 순서대로 내려간다. 도중에 없거나 맵이 아니면 null. */
    static Object at(Object root, String... keys) {
        Object cur = root;
        for (String key : keys) {
            if (!(cur instanceof Map<?, ?> map)) {
                return null;
            }
            cur = map.get(key);
        }
        return cur;
    }

    static String text(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    static Long number(Object value) {
        if (value instanceof Number n) {
            return n.longValue();
        }
        if (value instanceof String s && !s.isBlank()) {
            try {
                return Long.parseLong(s.trim());
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    /** 행 목록. 1건이면 배열이 아니라 객체 하나로 오는 API(버스)가 있어 둘 다 받는다. 맵이 아닌 원소는 버린다. */
    @SuppressWarnings("unchecked")
    static List<Map<String, Object>> rows(Object value) {
        List<Map<String, Object>> out = new ArrayList<>();
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
}
