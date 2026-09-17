#!/usr/bin/env node
// 공공데이터 xlsx → CSV(UTF-8, LF) 변환. 열린데이터광장 최신 배포분이 xlsx 로만 제공되어 로더가 읽을 CSV 로 바꾼다.
// 값은 그대로 옮기고(원천 원칙), 머리글이 여러 줄로 병합된 파일은 --header-rows 로 합친 뒤 --header 로 이름을 덮어쓴다.
//
// 사용:
//   node BE/scripts/data/xlsx-to-csv.mjs <입력.xlsx> <출력.csv> [--header-rows N] [--header a,b,c] [--sheet sheet1]
//   node BE/scripts/data/xlsx-to-csv.mjs bus-stop.xlsx BE/src/main/resources/data/bus/seoul-bus-stops_20260902.csv
//   node BE/scripts/data/xlsx-to-csv.mjs bike.xlsx out.csv --header-rows 4 --header 대여소번호,보관소명,자치구,상세주소,위도,경도,설치시기,LCD거치대수,QR거치대수,운영방식
//
// 출력에는 병합 전 원본 머리글도 찍는다 — 다음 배포분에서 열 구조가 바뀌면 여기서 드러난다.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { parseArgs } from 'node:util';

import { toCsv } from './lib/csv.mjs';
import { mergeHeaderRows, workbookRows } from './lib/xlsx.mjs';

function fail(message, code = 2) {
  console.error(message);
  process.exitCode = code; // process.exit() 는 Windows 에서 UV_HANDLE_CLOSING assertion 을 낸다
}

function main() {
  const { values: opt, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      'header-rows': { type: 'string', default: '1' },
      header: { type: 'string' },
      sheet: { type: 'string', default: 'sheet1' },
    },
  });
  if (positionals.length !== 2) {
    fail('사용: node BE/scripts/data/xlsx-to-csv.mjs <입력.xlsx> <출력.csv> [--header-rows N] [--header a,b,c] [--sheet sheet1]');
    return;
  }
  const [input, output] = positionals;
  const headerRows = Number(opt['header-rows']);
  if (!Number.isInteger(headerRows) || headerRows < 1) {
    fail(`--header-rows 는 1 이상의 정수여야 한다: ${opt['header-rows']}`);
    return;
  }

  const rows = workbookRows(readFileSync(input), opt.sheet);
  const original = mergeHeaderRows(rows.slice(0, headerRows));
  const header = opt.header ? opt.header.split(',').map((s) => s.trim()) : original;
  if (header.length !== original.length) {
    fail(`--header 열 수(${header.length})가 파일 머리글 열 수(${original.length})와 다르다.\n  파일 머리글: ${original.join(' | ')}`);
    return;
  }

  const body = rows.slice(headerRows);
  const data = body.filter((r) => r.some((v) => v !== ''));
  const csv = toCsv(header, data);
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, csv, 'utf8');

  console.log(`입력      ${input} (시트 ${opt.sheet})`);
  console.log(`머리글    ${headerRows}행 → ${original.join(' | ')}`);
  if (opt.header) console.log(`사용 헤더 ${header.join(' | ')}`);
  console.log(`데이터    ${data.length.toLocaleString()}행 (빈 행 ${(body.length - data.length).toLocaleString()}개 제외)`);
  console.log(`출력      ${output} (${csv.length.toLocaleString()}자, UTF-8, LF)`);
}

try {
  main();
} catch (err) {
  fail(`변환 실패: ${err.message}`, 1);
}
