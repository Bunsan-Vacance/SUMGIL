package com.ssafy.s15p21a104.domain.bike.repository;

import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPred;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredId;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BikeStockPredRepository extends JpaRepository<BikeStockPred, BikeStockPredId> {
}
