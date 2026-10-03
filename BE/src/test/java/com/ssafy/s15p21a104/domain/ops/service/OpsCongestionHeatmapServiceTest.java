package com.ssafy.s15p21a104.domain.ops.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.ops.dto.response.CongestionHeatmapResponse;
import com.ssafy.s15p21a104.domain.ops.dto.response.HeatmapCell;
import com.ssafy.s15p21a104.domain.ops.dto.response.HeatmapLine;
import com.ssafy.s15p21a104.domain.ops.repository.OpsCongestionPredRepository;
import com.ssafy.s15p21a104.domain.ops.repository.OpsCongestionPredRepository.HeatmapMeta;
import com.ssafy.s15p21a104.domain.ops.repository.OpsCongestionPredRepository.HeatmapRow;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class OpsCongestionHeatmapServiceTest {

    // UTC 2026-10-02 16:00 = KST 2026-10-03 01:00 — UTC 날짜와 서울 날짜가 다른 시각이다.
    private static final Clock CLOCK = Clock.fixed(Instant.parse("2026-10-02T16:00:00Z"), ZoneId.of("UTC"));
    private static final LocalDate DATE = LocalDate.of(2026, 10, 3);

    @Mock
    private OpsCongestionPredRepository repository;

    private OpsCongestionHeatmapService service;

    @BeforeEach
    void setUp() {
        service = new OpsCongestionHeatmapService(repository, CLOCK);
    }

    @Test
    @DisplayName("집계 행을 호선별로 묶어 슬롯 10~47 고정 축(38칸)으로 펼치고 빈 슬롯은 null 셀")
    void mapsRowsOntoFixedAxis() {
        givenRows(
                row("L2", "2호선", 10, 31.25, 40, 3, 55.0),
                row("L2", "2호선", 20, 70.0, 38, 0, 98.5),
                row("L9", "9호선", 47, 12.0, 10, 10, 20.0));
        givenMeta(meta(OffsetDateTime.parse("2026-10-02T20:00:00+09:00"),
                "v1,v2"));

        CongestionHeatmapResponse response = service.heatmap("2026-10-03");

        assertEquals(DATE, response.date());
        assertEquals("congestion_pred", response.source());
        assertEquals(10, response.slotFrom());
        assertEquals(47, response.slotTo());
        assertEquals(List.of("v1", "v2"), response.predictorVersions());
        assertEquals(OffsetDateTime.parse("2026-10-02T20:00:00+09:00"), response.generatedAt());
        assertEquals(2, response.lines().size());

        HeatmapLine l2 = response.lines().get(0);
        assertEquals("L2", l2.lineId());
        assertEquals("2호선", l2.lineName());
        assertEquals(38, l2.cells().size());
        assertEquals(10, l2.cells().get(0).timeSlot());
        assertEquals(47, l2.cells().get(37).timeSlot());

        HeatmapCell first = l2.cells().get(0);
        assertEquals(new BigDecimal("31.3"), first.level());
        assertEquals(40, first.nLinks());
        assertEquals(3, first.nFallback());
        assertEquals(new BigDecimal("55.0"), first.maxLevel());

        HeatmapCell slot20 = l2.cells().get(10);
        assertEquals(20, slot20.timeSlot());
        assertEquals(new BigDecimal("98.5"), slot20.maxLevel());

        HeatmapCell missing = l2.cells().get(1);
        assertEquals(11, missing.timeSlot());
        assertNull(missing.level());
        assertNull(missing.maxLevel());
        assertEquals(0, missing.nLinks());
        assertEquals(0, missing.nFallback());

        HeatmapCell l9Last = response.lines().get(1).cells().get(37);
        assertEquals(10, l9Last.nFallback());
        assertEquals(new BigDecimal("12.0"), l9Last.level());
    }

    @Test
    @DisplayName("집계 결과가 없으면 lines는 빈 목록, 버전 빈 목록, generatedAt null")
    void emptyResult() {
        when(repository.aggregateByLineAndSlot(DATE)).thenReturn(List.of());
        givenMeta(meta(null, null));

        CongestionHeatmapResponse response = service.heatmap("2026-10-03");

        assertTrue(response.lines().isEmpty());
        assertTrue(response.predictorVersions().isEmpty());
        assertNull(response.generatedAt());
        assertEquals("congestion_pred", response.source());
    }

    @Test
    @DisplayName("date 형식이 깨지면 BAD_REQUEST")
    void badDate() {
        DomainException exception = assertThrows(DomainException.class, () -> service.heatmap("2026/10/03"));

        assertEquals(ErrorType.BAD_REQUEST, exception.getErrorType());
    }

    @Test
    @DisplayName("date가 없으면 Clock 기준 Asia/Seoul 오늘을 쓴다")
    void defaultDateUsesSeoul() {
        when(repository.aggregateByLineAndSlot(DATE)).thenReturn(List.of());
        givenMeta(meta(null, null));

        CongestionHeatmapResponse response = service.heatmap(null);

        assertEquals(DATE, response.date());
        verify(repository).aggregateByLineAndSlot(DATE);
    }

    @Test
    @DisplayName("시각이 Instant로 와도 OffsetDateTime으로 변환한다")
    void generatedAtFromInstant() {
        when(repository.aggregateByLineAndSlot(DATE)).thenReturn(List.of());
        HeatmapMeta meta = mock(HeatmapMeta.class);
        when(meta.getGeneratedAt()).thenReturn(Instant.parse("2026-10-02T11:00:00Z"));
        when(meta.getPredictorVersions()).thenReturn("v1");
        when(repository.findMeta(DATE)).thenReturn(meta);

        CongestionHeatmapResponse response = service.heatmap("2026-10-03");

        assertEquals(Instant.parse("2026-10-02T11:00:00Z"), response.generatedAt().toInstant());
        assertEquals(List.of("v1"), response.predictorVersions());
    }

    private void givenRows(HeatmapRow... rows) {
        when(repository.aggregateByLineAndSlot(DATE)).thenReturn(List.of(rows));
    }

    private void givenMeta(HeatmapMeta meta) {
        when(repository.findMeta(DATE)).thenReturn(meta);
    }

    private static HeatmapRow row(String lineId, String lineName, int slot, double level, int links, int fallback,
                                  double maxLevel) {
        HeatmapRow row = mock(HeatmapRow.class);
        lenient().when(row.getLineId()).thenReturn(lineId);
        lenient().when(row.getLineName()).thenReturn(lineName);
        lenient().when(row.getTimeSlot()).thenReturn(slot);
        lenient().when(row.getLevel()).thenReturn(level);
        lenient().when(row.getLinkCount()).thenReturn((long) links);
        lenient().when(row.getFallbackCount()).thenReturn((long) fallback);
        lenient().when(row.getMaxLevel()).thenReturn(new BigDecimal(String.valueOf(maxLevel)));
        return row;
    }

    private static HeatmapMeta meta(OffsetDateTime generatedAt, String versions) {
        HeatmapMeta meta = mock(HeatmapMeta.class);
        lenient().when(meta.getGeneratedAt()).thenReturn(generatedAt);
        lenient().when(meta.getPredictorVersions()).thenReturn(versions);
        return meta;
    }
}
