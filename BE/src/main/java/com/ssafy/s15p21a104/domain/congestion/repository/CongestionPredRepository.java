package com.ssafy.s15p21a104.domain.congestion.repository;

import com.ssafy.s15p21a104.domain.congestion.entity.CongestionPred;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionPredId;
import java.time.LocalDate;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface CongestionPredRepository extends JpaRepository<CongestionPred, CongestionPredId> {

    Optional<CongestionPred> findById_PredDateAndId_FromStationIdAndId_ToStationIdAndId_LineIdAndId_DirectionAndId_TimeSlot(
            LocalDate predDate, String fromStationId, String toStationId, String lineId, String direction,
            Integer timeSlot);
}
