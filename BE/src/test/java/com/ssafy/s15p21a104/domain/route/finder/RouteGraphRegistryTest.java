package com.ssafy.s15p21a104.domain.route.finder;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import com.ssafy.s15p21a104.domain.route.repository.RouteEdgeTimeRepository;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.station.entity.Line;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.domain.station.repository.TransferMetaRepository;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * S15P21A104-122 Registry 배선 검증. DB 없이 green.
 */
@ExtendWith(MockitoExtension.class)
class RouteGraphRegistryTest {

    @Mock
    private RouteEdgeTimeRepository edgeTimeRepository;

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteLineRepository lineRepository;

    @Mock
    private TransferMetaRepository transferMetaRepository;

    @Mock
    private BikeStationRepository bikeStationRepository;

    @Test
    @DisplayName("122-T6: 접근은 WALK·본선은 대여소간 BIKE·역↔대여소 BIKE 없음")
    void t122_접근WALK_본선대여소간() {
        when(edgeTimeRepository.findSubwayEdgesForDefaultSlot())
                .thenReturn(List.of(new RouteEdgeRow("S1", "S2", "L1", 300, 0)));
        Station station1 = station("S1", 37.5000, 127.0000);
        Station station2 = station("S2", 37.5000, 127.0045);
        when(stationRepository.findAll()).thenReturn(List.of(station1, station2));
        Line line = mock(Line.class);
        when(line.getLineId()).thenReturn("L1");
        when(line.getName()).thenReturn("1호선");
        when(lineRepository.findAll()).thenReturn(List.of(line));
        BikeStation rental1 = rental("R1", 37.5000, 127.0005);
        BikeStation rental2 = rental("R2", 37.5000, 127.0040);
        when(bikeStationRepository.findAll()).thenReturn(List.of(rental1, rental2));
        when(transferMetaRepository.findAll()).thenReturn(List.of());

        RouteGraphRegistry registry = new RouteGraphRegistry(
                edgeTimeRepository, stationRepository, lineRepository,
                transferMetaRepository, bikeStationRepository);
        registry.load();

        assertNotNull(registry.graph());
        assertEquals(Set.of("R1", "R2"), registry.rentalIds());
        assertTrue(registry.graph().outgoingEdges("S1").stream()
                .noneMatch(e -> e.mode() == TravelMode.BIKE));
        assertTrue(registry.graph().outgoingEdges("S1").stream()
                .anyMatch(e -> e.mode() == TravelMode.WALK && e.toNode().equals("R1")));
        assertTrue(registry.graph().outgoingEdges("R1").stream()
                .anyMatch(e -> e.mode() == TravelMode.BIKE && e.toNode().equals("R2")));
        assertTrue(registry.stationInfos().containsKey("R1"));
    }

    private Station station(String id, double lat, double lng) {
        Station station = mock(Station.class);
        when(station.getStationId()).thenReturn(id);
        when(station.getName()).thenReturn(id + "역");
        when(station.getLat()).thenReturn(lat);
        when(station.getLng()).thenReturn(lng);
        return station;
    }

    private BikeStation rental(String id, double lat, double lng) {
        BikeStation rental = mock(BikeStation.class);
        when(rental.getRentalId()).thenReturn(id);
        when(rental.getName()).thenReturn(id + "대여소");
        when(rental.getLat()).thenReturn(lat);
        when(rental.getLng()).thenReturn(lng);
        return rental;
    }
}
