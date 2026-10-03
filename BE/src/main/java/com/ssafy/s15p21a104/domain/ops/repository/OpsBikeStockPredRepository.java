package com.ssafy.s15p21a104.domain.ops.repository;

import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPred;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredId;
import java.util.Collection;
import java.util.List;
import org.springframework.data.repository.Repository;

/** 운영자 뷰 전용 읽기 리포지토리 — 여러 대여소의 같은 (dow_type, time_slot) 예측을 한 번에 읽는다. */
public interface OpsBikeStockPredRepository extends Repository<BikeStockPred, BikeStockPredId> {

    List<BikeStockPred> findByIdRentalIdInAndIdDowTypeAndIdTimeSlot(
            Collection<String> rentalIds, Integer dowType, Integer timeSlot);
}
