#!/usr/bin/env node
/**
 * 로컬 부하 테스트 스크립트. 외부 도구(ab/wrk/k6) 설치 없이 Node만으로 동시 요청을 쏘고
 * 지연시간(p50/p95/p99)·처리량·에러율을 집계한다.
 *
 * 사용법:
 *   node scripts/loadtest/loadtest.mjs --base http://localhost:8080 --concurrency 20 --requests 500
 *
 * S15P21A104-75(시연용 배포 환경 구성) — 실제 배포 전, 로컬에서 먼저 성능 감을 잡기 위함.
 */

const args = Object.fromEntries(
    process.argv.slice(2).reduce((pairs, arg, i, arr) => {
        if (arg.startsWith("--")) {
            const key = arg.slice(2);
            const next = arr[i + 1];
            const value = next && !next.startsWith("--") ? next : "true";
            pairs.push([key, value]);
        }
        return pairs;
    }, [])
);

const BASE = args.base ?? "http://localhost:8080";
const CONCURRENCY = Number(args.concurrency ?? 10);
const TOTAL_REQUESTS = Number(args.requests ?? 200);

// 실제로 존재하는 역 ID 조합(2호선 역삼-강변, 환승 포함 강변-용산, 역 검색, 대여소 검색) 섞어서 현실적인 트래픽 흉내.
const SCENARIOS = [
    { name: "routes/search (단일 노선)", path: "/api/routes/search?originStationId=221&destStationId=214" },
    { name: "routes/search (환승 포함)", path: "/api/routes/search?originStationId=214&destStationId=1003" },
    { name: "stations/search", path: "/api/stations/search?query=%EA%B0%95%EB%82%A8" }, // 강남
    { name: "bike-stations/nearby", path: "/api/bike-stations/nearby?lat=37.5006&lng=127.0364" },
];

function pickScenario(i) {
    return SCENARIOS[i % SCENARIOS.length];
}

async function timedRequest(scenario) {
    const start = performance.now();
    try {
        const response = await fetch(BASE + scenario.path);
        const elapsed = performance.now() - start;
        return { scenario: scenario.name, status: response.status, elapsed, ok: response.ok };
    } catch (error) {
        const elapsed = performance.now() - start;
        return { scenario: scenario.name, status: 0, elapsed, ok: false, error: error.message };
    }
}

async function worker(queue, results) {
    while (queue.length > 0) {
        const i = queue.pop();
        results.push(await timedRequest(pickScenario(i)));
    }
}

function percentile(sortedLatencies, p) {
    const idx = Math.min(sortedLatencies.length - 1, Math.floor(sortedLatencies.length * p));
    return sortedLatencies[idx];
}

async function main() {
    console.log(`대상: ${BASE}, 동시성: ${CONCURRENCY}, 총 요청: ${TOTAL_REQUESTS}`);
    const queue = Array.from({ length: TOTAL_REQUESTS }, (_, i) => i);
    const results = [];
    const startedAt = performance.now();

    const workers = Array.from({ length: CONCURRENCY }, () => worker(queue, results));
    await Promise.all(workers);

    const totalElapsedSec = (performance.now() - startedAt) / 1000;
    const byScenario = new Map();
    for (const r of results) {
        if (!byScenario.has(r.scenario)) {
            byScenario.set(r.scenario, []);
        }
        byScenario.get(r.scenario).push(r);
    }

    console.log("\n=== 시나리오별 결과 ===");
    for (const [name, rows] of byScenario) {
        const latencies = rows.map((r) => r.elapsed).sort((a, b) => a - b);
        const errors = rows.filter((r) => !r.ok);
        console.log(`\n[${name}] 요청 ${rows.length}건, 에러 ${errors.length}건`);
        console.log(`  평균 ${avg(latencies).toFixed(1)}ms  p50 ${percentile(latencies, 0.5).toFixed(1)}ms  ` +
                `p95 ${percentile(latencies, 0.95).toFixed(1)}ms  p99 ${percentile(latencies, 0.99).toFixed(1)}ms  ` +
                `최대 ${latencies[latencies.length - 1].toFixed(1)}ms`);
        if (errors.length > 0) {
            const sample = errors[0];
            console.log(`  에러 예시: status=${sample.status} ${sample.error ?? ""}`);
        }
    }

    const allErrors = results.filter((r) => !r.ok).length;
    console.log(`\n=== 전체 ===`);
    console.log(`총 ${results.length}건, 에러 ${allErrors}건(${((allErrors / results.length) * 100).toFixed(1)}%), ` +
            `소요 ${totalElapsedSec.toFixed(1)}s, 처리량 ${(results.length / totalElapsedSec).toFixed(1)} req/s`);
}

function avg(arr) {
    return arr.reduce((a, b) => a + b, 0) / arr.length;
}

main();
