package com.ssafy.s15p21a104.domain.congestion.repository;

import com.ssafy.s15p21a104.domain.congestion.entity.Congestion;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionId;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface CongestionRepository extends JpaRepository<Congestion, CongestionId> {

    Optional<Congestion> findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
            CongestionTarget targetType, String targetId, Integer dowType, Integer timeSlot);
}
