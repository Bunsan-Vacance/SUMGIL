// k6 부하 테스트: 좌표 기반 경로 검색 POST /api/routes/search/coordinate (S15P21A104-154)
//
// 설치: winget install k6.k6  (또는 https://k6.io/docs/get-started/installation/)
// 실행:
//   k6 run scripts/loadtest/k6-coordinate-search.js
//   k6 run --env BASE_URL=http://localhost:8080 --env VUS=50 --env DURATION=1m scripts/loadtest/k6-coordinate-search.js
//
// 서울 시내 실제 역 좌표 몇 곳을 "건물 위치"로 흉내내 여러 출발·도착 조합을 돌아가며 쏜다.
// 실제 건물 좌표가 아니라 역 좌표를 그대로 써도 무방하다 — 접근 후보 탐색(반경 500m) 로직
// 입장에서는 "역 DB에 없는 임의 좌표"라는 점이 중요하지, 좌표 자체가 역과 정확히 같아도
// searchByCoordinate 경로를 그대로 탄다(PLACE-ORIGIN/PLACE-DEST 임시 노드로 처리).

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';
const VUS = Number(__ENV.VUS || 30);
const DURATION = __ENV.DURATION || '1m';

// 역삼·강남·신촌·잠실·건대입구·홍대입구 실좌표. 서로 거리가 있어 매번 다른 본이동 조합이 걸린다.
const PLACES = [
  { lat: 37.500658, lng: 127.036430, name: '역삼' },
  { lat: 37.497958, lng: 127.027539, name: '강남' },
  { lat: 37.555153, lng: 126.936890, name: '신촌' },
  { lat: 37.513305, lng: 127.100129, name: '잠실' },
  { lat: 37.540408, lng: 127.069231, name: '건대입구' },
  { lat: 37.556748, lng: 126.923643, name: '홍대입구' },
];

const routeCandidateCount = new Trend('route_candidate_count');
const accessNotFoundRate = new Rate('access_candidate_not_found_rate');

export const options = {
  scenarios: {
    coordinate_search: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '20s', target: Math.ceil(VUS / 2) }, // 웜업
        { duration: DURATION, target: VUS },
        { duration: '20s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],       // 실패율 1% 미만
    http_req_duration: ['p(95)<2000'],    // p95 2초 미만 (외부 카카오 API 호출이 껴서 역 검색보다 널널하게 잡음)
  },
};

function randomPlace(excludeName) {
  let place;
  do {
    place = PLACES[Math.floor(Math.random() * PLACES.length)];
  } while (place.name === excludeName);
  return place;
}

export default function () {
  const origin = randomPlace();
  const destination = randomPlace(origin.name);

  const payload = JSON.stringify({
    origin: { lat: origin.lat, lng: origin.lng, name: origin.name },
    destination: { lat: destination.lat, lng: destination.lng, name: destination.name },
  });

  const res = http.post(`${BASE_URL}/api/routes/search/coordinate`, payload, {
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'coordinate_search' },
  });

  const isAccessNotFound = res.status === 404;
  accessNotFoundRate.add(isAccessNotFound);

  check(res, {
    '200 or 404(접근 후보 없음, 정상 경계 케이스)': (r) => r.status === 200 || r.status === 404,
    '502 없음': (r) => r.status !== 502,
  });

  if (res.status === 200) {
    try {
      const body = JSON.parse(res.body);
      routeCandidateCount.add(body.data ? body.data.length : 0);
    } catch (e) {
      // 파싱 실패는 check 실패로 이미 걸러짐 없음 — 응답 형식 자체가 깨진 경우 콘솔에만 남긴다.
      console.error(`JSON 파싱 실패: ${e.message}`);
    }
  }

  sleep(0.3);
}
