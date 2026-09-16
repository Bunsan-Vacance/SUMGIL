#!/usr/bin/env node
// stations/search 최적화 전/후 비교 전용 — 넓은 검색어(많은 역 매칭)로 N+1 영향을 도드라지게 본다.
const BASE = process.argv.includes("--base")
    ? process.argv[process.argv.indexOf("--base") + 1]
    : "http://localhost:8080";
const CONCURRENCY = 50;
const TOTAL = 500;
const QUERY = encodeURIComponent("산"); // 49개 역 매칭

async function timedRequest() {
    const start = performance.now();
    const response = await fetch(`${BASE}/api/stations/search?query=${QUERY}`);
    await response.json();
    return performance.now() - start;
}

async function worker(queue, results) {
    while (queue.length > 0) {
        queue.pop();
        results.push(await timedRequest());
    }
}

function percentile(sorted, p) {
    return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))];
}

async function main() {
    const queue = Array.from({ length: TOTAL }, (_, i) => i);
    const results = [];
    const start = performance.now();
    await Promise.all(Array.from({ length: CONCURRENCY }, () => worker(queue, results)));
    const totalSec = (performance.now() - start) / 1000;
    const sorted = results.sort((a, b) => a - b);
    const avg = sorted.reduce((a, b) => a + b, 0) / sorted.length;
    console.log(`요청 ${sorted.length}건 (동시성 ${CONCURRENCY}, 검색어 "산" = 49개 역 매칭)`);
    console.log(`평균 ${avg.toFixed(1)}ms  p50 ${percentile(sorted, 0.5).toFixed(1)}ms  ` +
            `p95 ${percentile(sorted, 0.95).toFixed(1)}ms  p99 ${percentile(sorted, 0.99).toFixed(1)}ms  ` +
            `최대 ${sorted[sorted.length - 1].toFixed(1)}ms`);
    console.log(`처리량 ${(sorted.length / totalSec).toFixed(1)} req/s`);
}

main();
