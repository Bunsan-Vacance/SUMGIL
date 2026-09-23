package com.ssafy.s15p21a104.load.bikepreddaily;

import java.io.IOException;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * CSV 옆 사이드카 {@code .meta.json} (S15P21A104-309). AI {@code batch_predict.py} 가 쓰는 모양 그대로다:
 * <pre>{@code {"source": "model", "target_date": "2026-09-23", "rows": 135552, "generated_at": "2026-09-23T00:30:00+00:00", ...}}</pre>
 *
 * <p>avg 산출물도 같은 파일명·같은 사이드카를 쓰고 {@code target_date} 만 {@code null} 이다. 그래서
 * {@link #targetDateOf(String)} 가 비면 날짜축 산출물이 아니다.
 *
 * <p>JSON 파서를 들이지 않고 필요한 값만 정규식으로 뽑는다 — 혼잡도 사이드카({@code CongestionPredMeta})와 같다.
 *
 * @param rows        CSV 행 수(헤더 제외). 잘린 파일을 거른다
 * @param targetDate  대상 날짜. 폴더에서 날짜별 최신 회차를 고르는 키다(파일명에 날짜가 없다)
 * @param generatedAt 산출 시각. NOT NULL 열이고 응답 {@code predictedAt} 으로 나간다
 */
public record BikeStockPredDailyMeta(int rows, LocalDate targetDate, OffsetDateTime generatedAt) {

    private static final Pattern ROWS = Pattern.compile("\"rows\"\\s*:\\s*(\\d+)");
    private static final Pattern TARGET_DATE = Pattern.compile("\"target_date\"\\s*:\\s*\"(\\d{4}-\\d{2}-\\d{2})\"");
    private static final Pattern GENERATED_AT = Pattern.compile("\"generated_at\"\\s*:\\s*\"([^\"]+)\"");

    /** 날짜축 산출물이면 대상 날짜. avg 산출물({@code "target_date": null})이면 비어 있다. */
    public static Optional<LocalDate> targetDateOf(String text) {
        Matcher m = TARGET_DATE.matcher(text);
        return m.find() ? Optional.of(LocalDate.parse(m.group(1))) : Optional.empty();
    }

    /**
     * @throws IOException 세 값 중 하나라도 없거나 읽지 못할 때. <b>조용히 넘기지 않는다</b>
     */
    public static BikeStockPredDailyMeta parse(String text, String path) throws IOException {
        Matcher rows = ROWS.matcher(text);
        if (!rows.find()) {
            throw new IOException("사이드카 meta 에 rows 가 없습니다: " + path);
        }
        LocalDate targetDate = targetDateOf(text).orElseThrow(() ->
                new IOException("사이드카 meta 에 target_date 가 없습니다 — 날짜축 산출물이 아닙니다: " + path));
        Matcher generated = GENERATED_AT.matcher(text);
        if (!generated.find()) {
            throw new IOException("사이드카 meta 에 generated_at 이 없습니다 — bike_stock_pred_daily.generated_at 은"
                    + " NOT NULL 이라 넣을 값이 없습니다: " + path);
        }
        try {
            return new BikeStockPredDailyMeta(Integer.parseInt(rows.group(1)), targetDate,
                    OffsetDateTime.parse(generated.group(1)));
        } catch (DateTimeParseException e) {
            throw new IOException("사이드카 meta 의 generated_at 을 읽지 못했습니다: "
                    + generated.group(1) + " (" + path + ")", e);
        }
    }
}
