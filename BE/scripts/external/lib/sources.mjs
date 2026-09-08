// 외부 데이터 소스 3종의 엔드포인트·인증키·응답 판정 규칙.
// 소스별 쿼터·필드·함정은 BE/docs/external/api-survey.md 에 정리한다.

export const SOURCES = {
  subway: {
    label: '서울시 지하철 실시간 도착정보(일괄)',
    // 실시간 지하철은 열린데이터광장 일반키와 별도 인증키다. 전용 키가 없으면 일반키로 시도한다.
    envKeys: ['SEOUL_SUBWAY_KEY', 'SEOUL_API_KEY'],
    rowsPath: ['realtimeArrivalList'],
  },
  bike: {
    label: '서울시 공공자전거 실시간 대여정보(bikeList)',
    envKeys: ['SEOUL_BIKE_KEY', 'SEOUL_API_KEY'],
    rowsPath: ['rentBikeStatus', 'row'],
  },
  bus: {
    label: '서울특별시 버스도착정보조회(getLowArrInfoByStId)',
    // 공공데이터포털 serviceKey. .env 에는 디코딩(Decoding) 키를 넣는다 — URL 조립 시 인코딩된다.
    envKeys: ['DATA_GO_KR_KEY'],
    rowsPath: ['msgBody', 'itemList'],
  },
};

const OK_CODE = { subway: 'INFO-000', bike: 'INFO-000', bus: '0' };

export function spec(source) {
  const s = SOURCES[source];
  if (!s) {
    throw new Error(`알 수 없는 소스 '${source}'. 사용 가능: ${Object.keys(SOURCES).join(', ')}`);
  }
  return s;
}

export function buildUrl(source, key, opts = {}) {
  spec(source);
  switch (source) {
    case 'subway': {
      const base = `http://swopenapi.seoul.go.kr/api/subway/${key}/json/realtimeStationArrival`;
      if (opts.station) {
        const count = opts.count ?? 5;
        return `${base}/0/${count}/${encodeURIComponent(opts.station)}`;
      }
      return `${base}/ALL`;
    }
    case 'bike': {
      const start = opts.start ?? 1;
      const end = opts.end ?? 1000;
      return `http://openapi.seoul.go.kr:8088/${key}/json/bikeList/${start}/${end}/`;
    }
    case 'bus': {
      if (!opts.stId) {
        throw new Error('bus 소스는 정류소 ID(stId)가 필요합니다. --st-id <정류소ID> 를 넘기세요.');
      }
      const url = new URL('http://ws.bus.go.kr/api/rest/arrive/getLowArrInfoByStId');
      url.searchParams.set('serviceKey', key);
      url.searchParams.set('stId', String(opts.stId));
      url.searchParams.set('resultType', 'json');
      return url.toString();
    }
    default:
      throw new Error(`URL 조립 규칙이 없는 소스 '${source}'`);
  }
}

// 우선순위: 명시 키(--key) → 소스 전용 환경변수 → 일반 환경변수. 빈 문자열은 없는 것으로 본다.
export function resolveKey(source, env = {}, override) {
  if (override) return override;
  const { envKeys } = spec(source);
  for (const name of envKeys) {
    const value = env[name];
    if (typeof value === 'string' && value.trim() !== '') return value.trim();
  }
  throw new Error(
    `${source} 인증키가 없습니다. BE/.env 에 ${envKeys.join(' 또는 ')} 를 넣거나 --key 로 넘기세요.`,
  );
}

// 로그·문서에 URL을 남길 때 키를 가린다. 쿼리로 들어간 키는 인코딩된 형태도 함께 가린다.
export function redactKey(url, key) {
  if (!key) return url;
  const forms = new Set([key, encodeURIComponent(key)]);
  let out = url;
  for (const form of forms) out = out.split(form).join('{KEY}');
  return out;
}

function asArray(value) {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

// 응답 본문을 { ok, code, message, rows, total } 로 통일한다.
// 실패 시 rows 는 항상 빈 배열이다 — 오류 응답에 섞인 부분 데이터를 성공으로 오해하지 않기 위해서다.
export function parseResponse(source, body) {
  spec(source);
  if (body === null || typeof body !== 'object') {
    return { ok: false, code: null, message: '응답 본문이 JSON 객체가 아닙니다.', rows: [], total: null };
  }
  switch (source) {
    case 'subway': {
      // 정상이면 errorMessage 안에, 오류면 최상위에 code/message 가 온다.
      const head = body.errorMessage ?? body;
      const code = head.code ?? null;
      const ok = code === OK_CODE.subway;
      const rows = ok ? asArray(body.realtimeArrivalList) : [];
      return { ok, code, message: head.message ?? null, rows, total: head.total ?? (ok ? rows.length : null) };
    }
    case 'bike': {
      // 정상이면 rentBikeStatus.RESULT, 오류면 최상위 RESULT 로 온다.
      const wrap = body.rentBikeStatus;
      const result = wrap?.RESULT ?? body.RESULT ?? {};
      const code = result.CODE ?? null;
      const ok = code === OK_CODE.bike;
      const rows = ok ? asArray(wrap?.row) : [];
      return { ok, code, message: result.MESSAGE ?? null, rows, total: wrap?.list_total_count ?? null };
    }
    case 'bus': {
      const head = body.msgHeader ?? {};
      const code = head.headerCd != null ? String(head.headerCd) : null;
      const ok = code === OK_CODE.bus;
      // itemList 가 1건이면 배열이 아니라 객체 하나로 올 수 있다.
      const rows = ok ? asArray(body.msgBody?.itemList) : [];
      return { ok, code, message: head.headerMsg ?? null, rows, total: head.itemCount ?? null };
    }
    default:
      return { ok: false, code: null, message: `판정 규칙이 없는 소스 '${source}'`, rows: [], total: null };
  }
}
