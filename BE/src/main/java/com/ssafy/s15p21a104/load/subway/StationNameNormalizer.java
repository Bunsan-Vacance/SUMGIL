package com.ssafy.s15p21a104.load.subway;

import java.util.Map;
import java.util.regex.Pattern;

/**
 * 원천마다 다른 역명 표기를 물리 역 이름 하나로 맞춘다.
 * 규칙은 두 가지뿐이다: 괄호 부기 제거, 별칭 표 적용. "역" 접미 제거처럼 추측성 규칙은 두지 않는다.
 * 정본 표기는 서울교통공사 좌표 파일·실시간 API 쪽("서울", "총신대입구", "신내")이다.
 */
public final class StationNameNormalizer {

    private static final Pattern PARENTHETICAL = Pattern.compile("\\s*\\([^)]*\\)");

    private final Map<String, String> aliases;

    public StationNameNormalizer(Map<String, String> aliases) {
        this.aliases = Map.copyOf(aliases);
    }

    public String normalize(String raw) {
        if (raw == null) {
            return "";
        }
        String name = PARENTHETICAL.matcher(raw).replaceAll("").trim();
        return aliases.getOrDefault(name, name);
    }

    /**
     * {@link #normalize(String)} 에 더해 끝의 '역'을 뗀다. KTDB 노드("청량리역", "서울역(경의)")·표준데이터("판교역")처럼
     * 역명에 '역'을 붙여 쓰는 원천용이다. 별칭은 떼기 전후 둘 다 적용한다 — "서울역" 은 별칭으로 "서울" 이 되고, 한 글자 이름은 자르지 않는다.
     * 시각표·환승 파일처럼 '역'을 붙이지 않는 원천에는 {@link #normalize(String)} 을 써야 한다 ("역삼", "동대문역사문화공원" 은 그대로).
     */
    public String normalizeStation(String raw) {
        String name = normalize(raw);
        if (name.length() > 1 && name.endsWith("역")) {
            name = normalize(name.substring(0, name.length() - 1));
        }
        return name;
    }
}
