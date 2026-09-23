package com.ssafy.s15p21a104.domain.bike.repository;

import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredDaily;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredDailyId;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BikeStockPredDailyRepository extends JpaRepository<BikeStockPredDaily, BikeStockPredDailyId> {
}
