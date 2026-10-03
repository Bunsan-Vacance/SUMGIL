package com.ssafy.s15p21a104.domain.ops.service;

import com.ssafy.s15p21a104.domain.ops.dto.response.CongestionHeatmapResponse;
import com.ssafy.s15p21a104.domain.ops.dto.response.HeatmapCell;
import com.ssafy.s15p21a104.domain.ops.dto.response.HeatmapLine;
import com.ssafy.s15p21a104.domain.ops.repository.OpsCongestionPredRepository;
import com.ssafy.s15p21a104.domain.ops.repository.OpsCongestionPredRepository.HeatmapMeta;
import com.ssafy.s15p21a104.domain.ops.repository.OpsCongestionPredRepository.HeatmapRow;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 운영자 뷰용 혼잡도 예측 히트맵. {@code congestion_pred}를 호선×슬롯으로 집계한 결과를
 * 고정 슬롯 축(10~47)으로 펼친다. 읽기 전용이다.
 */
@Service
@Transactional(readOnly = true)
public class OpsCongestionHeatmapService {

    static final String SOURCE = "congestion_pred";
    static final int SLOT_FROM = 10;
    static final int SLOT_TO = 47;
    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");

    private final OpsCongestionPredRepository repository;
    private final Clock clock;

    /** 운영 생성자 — Clock 빈이 프로파일별로만 있어 시스템 시계를 직접 쓴다(테스트는 Clock 받는 생성자). */
    @Autowired
    public OpsCongestionHeatmapService(OpsCongestionPredRepository repository) {
        this(repository, Clock.system(SEOUL));
    }

    OpsCongestionHeatmapService(OpsCongestionPredRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    public CongestionHeatmapResponse heatmap(String dateText) {
        LocalDate date = resolveDate(dateText);
        List<HeatmapRow> rows = repository.aggregateByLineAndSlot(date);
        HeatmapMeta meta = repository.findMeta(date);

        OffsetDateTime generatedAt = meta == null ? null : toOffset(meta.getGeneratedAt());
        List<String> versions = meta == null || meta.getPredictorVersions() == null
                || meta.getPredictorVersions().isBlank()
                ? List.of()
                : Arrays.stream(meta.getPredictorVersions().split(",")).map(String::trim)
                        .filter(v -> !v.isEmpty()).toList();

        // 호선 순서는 쿼리의 ORDER BY(line_id)를 그대로 따른다.
        Map<String, String> names = new LinkedHashMap<>();
        Map<String, Map<Integer, HeatmapCell>> cellsByLine = new LinkedHashMap<>();
        for (HeatmapRow row : rows) {
            names.putIfAbsent(row.getLineId(), row.getLineName());
            cellsByLine.computeIfAbsent(row.getLineId(), k -> new LinkedHashMap<>())
                    .put(row.getTimeSlot(), new HeatmapCell(row.getTimeSlot(), toLevel(row.getLevel()),
                            row.getLinkCount().intValue(), row.getFallbackCount().intValue(),
                            toLevel(row.getMaxLevel())));
        }

        List<HeatmapLine> lines = new ArrayList<>();
        cellsByLine.forEach((lineId, cells) -> {
            List<HeatmapCell> axis = new ArrayList<>(SLOT_TO - SLOT_FROM + 1);
            for (int slot = SLOT_FROM; slot <= SLOT_TO; slot++) {
                axis.add(cells.getOrDefault(slot, new HeatmapCell(slot, null, 0, 0, null)));
            }
            lines.add(new HeatmapLine(lineId, names.get(lineId), axis));
        });
        return new CongestionHeatmapResponse(date, SOURCE, generatedAt, versions, SLOT_FROM, SLOT_TO, lines);
    }

    private LocalDate resolveDate(String dateText) {
        if (dateText == null || dateText.isBlank()) {
            return LocalDate.now(clock.withZone(SEOUL));
        }
        try {
            return LocalDate.parse(dateText);
        } catch (DateTimeParseException e) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
    }

    /** percentile_cont는 double precision이라 부동소수 잡음이 있다 — 원천 scale(1)로 맞춘다. */
    private static BigDecimal toLevel(Number value) {
        if (value == null) {
            return null;
        }
        BigDecimal decimal = value instanceof BigDecimal b ? b : new BigDecimal(value.toString());
        return decimal.setScale(1, RoundingMode.HALF_UP);
    }

    private static OffsetDateTime toOffset(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof OffsetDateTime o) {
            return o;
        }
        if (value instanceof ZonedDateTime z) {
            return z.toOffsetDateTime();
        }
        if (value instanceof Instant i) {
            return i.atZone(SEOUL).toOffsetDateTime();
        }
        if (value instanceof Timestamp t) {
            return t.toInstant().atZone(SEOUL).toOffsetDateTime();
        }
        throw new IllegalStateException("지원하지 않는 시각 타입: " + value.getClass());
    }
}
