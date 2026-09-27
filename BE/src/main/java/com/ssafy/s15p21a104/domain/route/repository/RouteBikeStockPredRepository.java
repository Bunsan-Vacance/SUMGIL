package com.ssafy.s15p21a104.domain.route.repository;

import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPred;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredId;
import java.util.List;
import org.springframework.data.repository.Repository;

/**
 * 탐색 재고 게이트용 읽기 전용 조회 — {@code bike_stock_pred} 슬롯 단위 전체 대여소.
 * bike 도메인 리포지토리를 건드리지 않으려고 route 쪽에 둔다.
 */
public interface RouteBikeStockPredRepository extends Repository<BikeStockPred, BikeStockPredId> {

    List<BikeStockPred> findAllById_DowTypeAndId_TimeSlot(Integer dowType, Integer timeSlot);
}
