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
}
