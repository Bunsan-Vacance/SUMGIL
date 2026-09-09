// xlsx 시트 XML → 행 배열, 병합 머리글 → 한 줄 헤더 규칙을 고정하는 테스트.
// 열린데이터광장 최신 파일이 xlsx 로만 제공되어 의존성 없이 읽어야 한다 (BE/scripts/data/README.md).
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { mergeHeaderRows, sheetRows } from '../lib/xlsx.mjs';

const SHARED = `<?xml version="1.0"?>
<sst count="3" uniqueCount="3">
  <si><t>NODE_ID</t></si>
  <si><t>정류소명</t></si>
  <si><r><t>한강버스.</t></r><r><t>잠실선착장</t></r></si>
</sst>`;

describe('sheetRows', () => {
  test('공유 문자열·숫자·인라인 문자열 셀을 문자열로 읽는다', () => {
    const sheet = `<worksheet><sheetData>
      <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
      <row r="2"><c r="A2"><v>123000689</v></c><c r="B2" t="s"><v>2</v></c><c r="C2" t="inlineStr"><is><t>중앙차로</t></is></c></row>
    </sheetData></worksheet>`;

    assert.deepEqual(sheetRows(sheet, SHARED), [
      ['NODE_ID', '정류소명'],
      ['123000689', '한강버스.잠실선착장', '중앙차로'],
    ]);
  });

  test('비어 있는 중간 셀은 빈 문자열로 채워 열 위치를 유지한다', () => {
    const sheet = `<worksheet><sheetData>
      <row r="1"><c r="A1"><v>1</v></c><c r="C1"><v>3</v></c></row>
    </sheetData></worksheet>`;

    assert.deepEqual(sheetRows(sheet, SHARED), [['1', '', '3']]);
  });

  test('XML 엔티티를 원래 문자로 되돌린다 — &amp; → &', () => {
    const sheet = `<worksheet><sheetData>
      <row r="1"><c r="A1" t="inlineStr"><is><t>A&amp;B &lt;C&gt;</t></is></c></row>
    </sheetData></worksheet>`;

    assert.deepEqual(sheetRows(sheet, SHARED), [['A&B <C>']]);
  });

  test('공유 문자열 XML 이 없어도 인라인·숫자 셀은 읽는다', () => {
    const sheet = `<worksheet><sheetData>
      <row r="1"><c r="A1"><v>7</v></c></row>
    </sheetData></worksheet>`;

    assert.deepEqual(sheetRows(sheet, ''), [['7']]);
  });
});

describe('mergeHeaderRows', () => {
  test('여러 줄 머리글을 열마다 이어 붙이고 공백·줄바꿈을 없앤다', () => {
    // 따릉이 대여소 정보(OA-13252) 머리글 축소판: "대여소\n번호" 가 두 줄, "소재지(위치)" 가 4열 병합
    const rows = [
      ['대여소\n번호', '보관소(대여소)명', '소재지(위치)', '', '', '', '설치형태', ''],
      ['', '', '', '', '', '', 'LCD', 'QR'],
      ['', '', '자치구', '상세주소', '위도', '경도', '', ''],
      ['', '', '', '', '', '', '거치\n대수', '거치\n대수'],
    ];

    // 병합 셀의 값은 첫 열에만 있어 "소재지(위치)자치구"·"설치형태LCD거치대수" 처럼 붙는다.
    // 깔끔한 이름은 CLI 의 --header 로 덮어쓰고, 이 원본 머리글은 파일 구조 변경을 잡는 데 쓴다.
    assert.deepEqual(mergeHeaderRows(rows), [
      '대여소번호', '보관소(대여소)명', '소재지(위치)자치구', '상세주소', '위도', '경도', '설치형태LCD거치대수', 'QR거치대수',
    ]);
  });

  test('한 줄 머리글은 공백만 정리해 그대로 돌려준다', () => {
    assert.deepEqual(mergeHeaderRows([['NODE_ID', ' ARS_ID ', '정류소명']]), ['NODE_ID', 'ARS_ID', '정류소명']);
  });

  test('행 길이가 다르면 가장 긴 행 기준으로 열을 맞춘다', () => {
    assert.deepEqual(mergeHeaderRows([['a', 'b'], ['', '', 'c']]), ['a', 'b', 'c']);
  });
});
