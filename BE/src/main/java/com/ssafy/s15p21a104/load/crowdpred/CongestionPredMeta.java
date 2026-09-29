package com.ssafy.s15p21a104.load.crowdpred;

import java.io.IOException;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * CSV 옆에 붙는 사이드카 {@code .meta.json} (S15P21A104-305, AI 통지 07 2절).
 *
 * <p>키가 셋뿐이다:
 * <pre>{@code {"target_date": "2026-09-20", "row_count": 21684, "generated_at": "2026-09-20T23:43:00+09:00"}}</pre>
 *
 * <p>AI 에게는 날짜당 하나인 풍부한 meta 가 따로 있지만 그건 같은 날짜를 다시 만들면 <b>덮어써진다</b> —
 * CSV 는 {@code _HHMMSS} 로 쌓이므로 이전 CSV 가 짝을 잃는다. 그래서 CSV 마다 독립 사이드카를 둔다.
 *
 * <p>JSON 파서를 들이지 않고 필요한 두 값만 정규식으로 뽑는다(재고 예측 원천과 같은 방식). 키가 셋뿐이고
 * 중첩이 없어 파서를 들일 이유가 없다.
 *
 * @param rowCount    CSV 행 수(헤더 제외). 전송이 끊긴 파일을 적재 전에 거르는 데 쓴다
 * @param generatedAt 산출 시각. 파일명의 {@code _HHMMSS} 와 같은 순간이고
 *                    {@code congestion_pred.generated_at}(NOT NULL) 에 그대로 들어간다 — 재적재 판정 근거다
 */
public record CongestionPredMeta(int rowCount, OffsetDateTime generatedAt) {

    private static final Pattern ROW_COUNT = Pattern.compile("\"row_count\"\\s*:\\s*(\\d+)");
    private static final Pattern GENERATED_AT = Pattern.compile("\"generated_at\"\\s*:\\s*\"([^\"]+)\"");

    /**
     * @param text 사이드카 본문
     * @param path 오류 메시지에 밝힐 경로
     * @throws IOException 두 키 중 하나라도 없거나 시각을 읽지 못할 때. <b>조용히 넘기지 않는다</b> —
     *                     {@code generated_at} 은 NOT NULL 열이라 없으면 넣을 값이 없다
     */
    public static CongestionPredMeta parse(String text, String path) throws IOException {
        Matcher rows = ROW_COUNT.matcher(text);
        if (!rows.find()) {
            throw new IOException("사이드카 meta 에 row_count 가 없습니다: " + path);
        }
        Matcher generated = GENERATED_AT.matcher(text);
        if (!generated.find()) {
            throw new IOException("사이드카 meta 에 generated_at 이 없습니다 — congestion_pred.generated_at 은"
                    + " NOT NULL 이라 넣을 값이 없습니다: " + path);
        }
        try {
            return new CongestionPredMeta(Integer.parseInt(rows.group(1)),
                    OffsetDateTime.parse(generated.group(1)));
        } catch (DateTimeParseException e) {
            throw new IOException("사이드카 meta 의 generated_at 을 읽지 못했습니다: "
                    + generated.group(1) + " (" + path + ")", e);
        }
    }
}
