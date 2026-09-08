package com.ssafy.s15p21a104.domain.station.repository;

import com.ssafy.s15p21a104.domain.station.entity.Station;
import org.springframework.data.jpa.repository.JpaRepository;

public interface StationRepository extends JpaRepository<Station, String> {
}
