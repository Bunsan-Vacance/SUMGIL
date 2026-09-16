// ZIP 컨테이너 최소 판독기. xlsx(= ZIP 안의 XML 몇 개)를 외부 의존성 없이 열기 위한 것이다.
// 지원: 무압축(0)·deflate(8), 중앙 디렉터리 기반 탐색. ZIP64·암호화·다중 볼륨은 지원하지 않는다.
import { inflateRawSync } from 'node:zlib';

const SIG_EOCD = 0x06054b50; // End of central directory
const SIG_CDFH = 0x02014b50; // Central directory file header
const SIG_LFH = 0x04034b50; // Local file header

/** @returns {Map<string, Buffer>} 항목 이름 → 압축 해제된 내용 */
export function readZip(buf) {
  const eocd = findEocd(buf);
  const count = buf.readUInt16LE(eocd + 10);
  const cdOffset = buf.readUInt32LE(eocd + 16);
  if (cdOffset === 0xffffffff) throw new Error('ZIP64 형식은 지원하지 않는다');

  const entries = new Map();
  let p = cdOffset;
  for (let i = 0; i < count; i += 1) {
    if (buf.readUInt32LE(p) !== SIG_CDFH) throw new Error(`중앙 디렉터리 서명 불일치 (항목 ${i})`);
    const method = buf.readUInt16LE(p + 10);
    const compSize = buf.readUInt32LE(p + 20);
    const nameLen = buf.readUInt16LE(p + 28);
    const extraLen = buf.readUInt16LE(p + 30);
    const commentLen = buf.readUInt16LE(p + 32);
    const localOffset = buf.readUInt32LE(p + 42);
    const name = buf.toString('utf8', p + 46, p + 46 + nameLen);

    if (buf.readUInt32LE(localOffset) !== SIG_LFH) throw new Error(`로컬 헤더 서명 불일치: ${name}`);
    const localNameLen = buf.readUInt16LE(localOffset + 26);
    const localExtraLen = buf.readUInt16LE(localOffset + 28);
    const dataStart = localOffset + 30 + localNameLen + localExtraLen;
    const data = buf.subarray(dataStart, dataStart + compSize);

    if (method === 0) entries.set(name, data);
    else if (method === 8) entries.set(name, inflateRawSync(data));
    else throw new Error(`지원하지 않는 압축 방식 ${method}: ${name}`);

    p += 46 + nameLen + extraLen + commentLen;
  }
  return entries;
}

// EOCD 는 파일 끝에서 최대 65,535바이트(주석) 앞까지 뒤로 훑어 찾는다.
function findEocd(buf) {
  const min = Math.max(0, buf.length - 22 - 0xffff);
  for (let p = buf.length - 22; p >= min; p -= 1) {
    if (buf.readUInt32LE(p) === SIG_EOCD) return p;
  }
  throw new Error('ZIP 파일이 아니다 (EOCD 없음)');
}
