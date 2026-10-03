package com.ssafy.s15p21a104.domain.ops.repository;

import com.ssafy.s15p21a104.domain.congestion.entity.CongestionPred;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionPredId;
import java.time.LocalDate;
import java.util.List;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

/** 운영자 뷰 히트맵용 읽기 전용 집계 쿼리. */
public interface OpsCongestionPredRepository extends Repository<CongestionPred, CongestionPredId> {

    /**
     * 호선×슬롯 집계. ok·calibration_fallback 행만 쓰고(segment_truncated 등은 제외) level 중앙값을 낸다.
     */
    @Query(value = """
            SELECT p.line_id AS "lineId", l.name AS "lineName", p.time_slot AS "timeSlot",
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY p.level) AS "level",
                   COUNT(*) AS "linkCount",
                   COUNT(*) FILTER (WHERE p.data_status = 'calibration_fallback') AS "fallbackCount",
                   MAX(p.level) AS "maxLevel"
            FROM congestion_pred p
            JOIN line l ON l.line_id = p.line_id
            WHERE p.pred_date = :date
              AND p.data_status IN ('ok', 'calibration_fallback')
              AND p.level IS NOT NULL
            GROUP BY p.line_id, l.name, p.time_slot
            ORDER BY p.line_id, p.time_slot
            """, nativeQuery = true)
    List<HeatmapRow> aggregateByLineAndSlot(@Param("date") LocalDate date);

    /** 해당 날짜 전체 행 기준 산출 시각·예측기 버전(콤마 구분). 행이 없으면 두 값 모두 null. */
    @Query(value = """
            SELECT MAX(p.generated_at) AS "generatedAt",
                   STRING_AGG(DISTINCT p.predictor_version, ',') AS "predictorVersions"
            FROM congestion_pred p
            WHERE p.pred_date = :date
            """, nativeQuery = true)
    HeatmapMeta findMeta(@Param("date") LocalDate date);

    /**
     * 네이티브 결과는 드라이버·Hibernate 버전에 따라 숫자·시각 타입이 달라지므로(percentile_cont는 double precision)
     * Number·Object로 받고 서비스에서 정규화한다.
     */
    interface HeatmapRow {
        String getLineId();

        String getLineName();

        Integer getTimeSlot();

        Number getLevel();

        Number getLinkCount();

        Number getFallbackCount();

        Number getMaxLevel();
    }

    interface HeatmapMeta {
        Object getGeneratedAt();

        String getPredictorVersions();
    }
}
