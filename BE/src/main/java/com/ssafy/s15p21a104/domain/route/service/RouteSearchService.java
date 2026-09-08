package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.route.dto.request.RoutePriority;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * TODO: 경로 그래프·다익스트라 구현(S15P21A104-94~98)이 준비되면 mock 후보 생성을
 * 실제 알고리즘 호출로 교체한다. BE/docs/api/api-spec.md 참고.
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class RouteSearchService {

    private final StationRepository stationRepository;

    public List<RouteSearchResponse> search(
            String originStationId,
            String destStationId,
            List<TravelMode> modes,
            RoutePriority priority
    ) {
        if (originStationId.equals(destStationId)) {
            throw new DomainException(ErrorType.SAME_ORIGIN_DEST);
        }

        Station origin = findStation(originStationId);
        Station dest = findStation(destStationId);

        List<RouteSearchResponse> candidates = mockCandidates(origin, dest);
        return filterByModes(candidates, modes);
    }

    private Station findStation(String stationId) {
        return stationRepository.findById(stationId)
                .orElseThrow(() -> new DomainException(ErrorType.STATION_NOT_FOUND));
    }

    private List<RouteSearchResponse> mockCandidates(Station origin, Station dest) {
        RouteLegResponse subwayLeg = new RouteLegResponse(
                TravelMode.SUBWAY,
                origin.getStationId(), origin.getName(), origin.getLat(), origin.getLng(),
                dest.getStationId(), dest.getName(), dest.getLat(), dest.getLng(),
                null, 15.6
        );
        RouteLegResponse bikeLeg = new RouteLegResponse(
                TravelMode.BIKE,
                origin.getStationId(), origin.getName(), origin.getLat(), origin.getLng(),
                dest.getStationId(), dest.getName(), dest.getLat(), dest.getLng(),
                null, 13.2
        );

        List<RouteSearchResponse> candidates = new ArrayList<>();
        candidates.add(new RouteSearchResponse(RouteType.SHORTEST_WITH_BIKE, 13.2, List.of(bikeLeg), RouteSource.MOCK));
        candidates.add(new RouteSearchResponse(RouteType.SHORTEST, 15.6, List.of(subwayLeg), RouteSource.MOCK));
        candidates.sort(Comparator.comparing(RouteSearchResponse::totalMinutes));
        return candidates;
    }

    private List<RouteSearchResponse> filterByModes(List<RouteSearchResponse> candidates, List<TravelMode> modes) {
        if (modes == null || modes.isEmpty()) {
            return candidates;
        }
        return candidates.stream()
                .filter(candidate -> candidate.legs().stream()
                        .allMatch(leg -> isAlwaysAllowed(leg.mode()) || modes.contains(leg.mode())))
                .toList();
    }

    private boolean isAlwaysAllowed(TravelMode mode) {
        return mode == TravelMode.WALK || mode == TravelMode.TRANSFER;
    }
}
