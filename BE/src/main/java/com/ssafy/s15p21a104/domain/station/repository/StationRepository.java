package com.ssafy.s15p21a104.domain.station.repository;

import com.ssafy.s15p21a104.domain.station.entity.Station;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface StationRepository extends JpaRepository<Station, String> {

    /** 부분 검색(대소문자 무시) 후보. 순위·정렬·개수 제한은 서비스에서 처리한다. */
    List<Station> findByNameContainingIgnoreCase(String name);

    /** 위경도 사각형(bbox) 안의 역 후보. 정확한 반경 판정은 서비스에서 한다. */
    List<Station> findByLatBetweenAndLngBetween(Double latMin, Double latMax, Double lngMin, Double lngMax);
}
