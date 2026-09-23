package com.ssafy.s15p21a104.domain.route.bus.geometry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class KakaoPublicTrafficGeometryMapperTest {

    private static final double FROM_LAT = 37.5000;
    private static final double FROM_LNG = 127.0000;
    private static final double TO_LAT = 37.5010;
    private static final double TO_LNG = 127.0010;

    @Test
    @DisplayName("현재 버스 노선·정류소·끝점이 모두 맞으면 geometry를 반환한다")
    void matchingBusStep() {
        List<List<Double>> points = List.of(
                List.of(FROM_LNG, FROM_LAT), List.of(127.0005, 37.5005), List.of(TO_LNG, TO_LAT));
        KakaoPublicTrafficResponse response = response(
                new KakaoPublicTrafficResponse.Step(
                        new KakaoPublicTrafficResponse.Properties("BUS", List.of(
                                new KakaoPublicTrafficResponse.Stop("출발 정류장"),
                                new KakaoPublicTrafficResponse.Stop("도착 정류장")),
                                List.of(new KakaoPublicTrafficResponse.Vehicle("147")), 120),
                        new KakaoPublicTrafficResponse.Path(points)));

        Optional<MultiLineStringResponse> result = KakaoPublicTrafficGeometryMapper.toMultiLineString(
                response, "147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG);

        assertTrue(result.isPresent());
        assertEquals(points, result.orElseThrow().coordinates().get(0));
    }

    @Test
    @DisplayName("공식 publictraffic JSON을 역직렬화해 147번 BUS geometry를 얻는다")
    void officialResponseJson() throws Exception {
        String json = """
                {
                  "status": "OK",
                  "routes": [
                    {
                      "properties": {"type": "BUS", "totalDistance": 2100, "totalTime": 420, "transfers": 0},
                      "steps": [
                        {
                          "properties": {
                            "type": "BUS",
                            "time": 120,
                            "vehicles": [{"name": "147", "type": "간선"}],
                            "stops": [
                              {"name": "출발 정류장", "id": "stop-a"},
                              {"name": "도착 정류장", "id": "stop-c"}
                            ]
                          },
                          "path": {
                            "points": [[127.0, 37.5], [127.0005, 37.5005], [127.001, 37.501]]
                          }
                        }
                      ]
                    }
                  ]
                }
                """;

        KakaoPublicTrafficResponse response = new ObjectMapper()
                .readValue(json, KakaoPublicTrafficResponse.class);

        Optional<MultiLineStringResponse> result = KakaoPublicTrafficGeometryMapper.toMultiLineString(
                response, "147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG);

        assertTrue(result.isPresent());
        assertEquals(3, result.orElseThrow().coordinates().get(0).size());
    }

    @Test
    @DisplayName("노선명·정류소 순서·끝점이 맞지 않으면 geometry를 반환하지 않는다")
    void mismatchIsRejected() {
        List<List<Double>> points = List.of(List.of(FROM_LNG, FROM_LAT), List.of(TO_LNG, TO_LAT));
        for (KakaoPublicTrafficResponse.Step step : List.of(
                new KakaoPublicTrafficResponse.Step(new KakaoPublicTrafficResponse.Properties(
                        "BUS", List.of(new KakaoPublicTrafficResponse.Stop("출발 정류장"),
                                new KakaoPublicTrafficResponse.Stop("도착 정류장")),
                        List.of(new KakaoPublicTrafficResponse.Vehicle("999")), 120),
                        new KakaoPublicTrafficResponse.Path(points)),
                new KakaoPublicTrafficResponse.Step(new KakaoPublicTrafficResponse.Properties(
                        "BUS", List.of(new KakaoPublicTrafficResponse.Stop("도착 정류장"),
                                new KakaoPublicTrafficResponse.Stop("출발 정류장")),
                        List.of(new KakaoPublicTrafficResponse.Vehicle("147")), 120),
                        new KakaoPublicTrafficResponse.Path(points)),
                new KakaoPublicTrafficResponse.Step(new KakaoPublicTrafficResponse.Properties(
                        "BUS", List.of(new KakaoPublicTrafficResponse.Stop("출발 정류장"),
                                new KakaoPublicTrafficResponse.Stop("도착 정류장")),
                        List.of(new KakaoPublicTrafficResponse.Vehicle("147")), 120),
                        new KakaoPublicTrafficResponse.Path(List.of(
                                List.of(FROM_LNG + 0.01, FROM_LAT), List.of(TO_LNG, TO_LAT)))))) {
            assertTrue(KakaoPublicTrafficGeometryMapper.toMultiLineString(
                    response(step), "147", "출발 정류장", "도착 정류장",
                    FROM_LAT, FROM_LNG, TO_LAT, TO_LNG).isEmpty());
        }
    }

    @Test
    @DisplayName("실패 응답과 잘못된 path는 unavailable로 남긴다")
    void failureIsUnavailable() {
        assertTrue(KakaoPublicTrafficGeometryMapper.toMultiLineString(
                new KakaoPublicTrafficResponse("ERROR", List.of()),
                "147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG).isEmpty());

        KakaoPublicTrafficResponse invalidPath = response(
                new KakaoPublicTrafficResponse.Step(
                        new KakaoPublicTrafficResponse.Properties("BUS", List.of(
                                new KakaoPublicTrafficResponse.Stop("출발 정류장"),
                                new KakaoPublicTrafficResponse.Stop("도착 정류장")),
                                List.of(new KakaoPublicTrafficResponse.Vehicle("147")), 120),
                        new KakaoPublicTrafficResponse.Path(List.of(List.of(FROM_LNG, FROM_LAT)))));
        assertTrue(KakaoPublicTrafficGeometryMapper.toMultiLineString(
                invalidPath, "147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG).isEmpty());

        KakaoPublicTrafficResponse outOfRange = response(
                new KakaoPublicTrafficResponse.Step(
                        new KakaoPublicTrafficResponse.Properties("BUS", List.of(
                                new KakaoPublicTrafficResponse.Stop("출발 정류장"),
                                new KakaoPublicTrafficResponse.Stop("도착 정류장")),
                                List.of(new KakaoPublicTrafficResponse.Vehicle("147")), 120),
                        new KakaoPublicTrafficResponse.Path(List.of(
                                List.of(181.0, FROM_LAT), List.of(TO_LNG, TO_LAT)))));
        assertTrue(KakaoPublicTrafficGeometryMapper.toMultiLineString(
                outOfRange, "147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG).isEmpty());
    }

    @Test
    @DisplayName("BUS geometry는 성공만 캐시하고 실패는 재조회한다")
    void cacheOnlySuccess() {
        KakaoPublicTrafficClient client = mock(KakaoPublicTrafficClient.class);
        BusGeometryRegistry registry = new BusGeometryRegistry(client);
        MultiLineStringResponse geometry = MultiLineStringResponse.of(List.of(List.of(
                List.of(FROM_LNG, FROM_LAT), List.of(TO_LNG, TO_LAT))));
        when(client.fetchGeometry("147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG)).thenReturn(Optional.of(geometry));

        assertTrue(registry.geometryFor("R1", "A", "C", "147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG).isPresent());
        assertTrue(registry.geometryFor("R1", "A", "C", "147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG).isPresent());
        verify(client).fetchGeometry("147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG);

        when(client.fetchGeometry("147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG)).thenReturn(Optional.empty());
        BusGeometryRegistry failing = new BusGeometryRegistry(client);
        assertTrue(failing.geometryFor("R1", "A", "C", "147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG).isEmpty());
        assertTrue(failing.geometryFor("R1", "A", "C", "147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG).isEmpty());
        verify(client, org.mockito.Mockito.times(3)).fetchGeometry("147", "출발 정류장", "도착 정류장",
                FROM_LAT, FROM_LNG, TO_LAT, TO_LNG);
    }

    private KakaoPublicTrafficResponse response(KakaoPublicTrafficResponse.Step step) {
        return new KakaoPublicTrafficResponse(
                "OK", List.of(new KakaoPublicTrafficResponse.Route(List.of(step))));
    }
}
