package com.ssafy.s15p21a104.domain.bike.repository;

import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface BikeStationRepository extends JpaRepository<BikeStation, String> {

    List<BikeStation> findByLatBetweenAndLngBetween(Double latMin, Double latMax, Double lngMin, Double lngMax);
}
