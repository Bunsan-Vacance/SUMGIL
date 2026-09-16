package com.ssafy.s15p21a104.load.csv;

import java.io.IOException;
import java.io.Reader;
import java.io.StringReader;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

/**
 * 공공데이터 CSV 최소 파서. 헤더 1행, RFC 4180 따옴표 규칙, UTF-8 BOM·CRLF·빈 줄 허용.
 * 외부 의존성을 두지 않기 위해 직접 구현한다. 작은 파일은 {@link #parse(String)} 로 통째로,
 * 큰 파일(열차운행시각표 42만 행)은 {@link #forEachRow(Reader, Consumer)} 로 행마다 콜백으로 읽는다 — 규칙은 같다.
 */
public final class CsvTable {

    private final List<String> headers;
    private final List<Map<String, String>> rows;

    private CsvTable(List<String> headers, List<Map<String, String>> rows) {
        this.headers = List.copyOf(headers);
        this.rows = List.copyOf(rows);
    }

    public static CsvTable parse(String text) {
        List<String> headers = new ArrayList<>();
        List<Map<String, String>> rows = new ArrayList<>();
        try {
            scan(new StringReader(text), headers, rows::add);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        return new CsvTable(headers, rows);
    }

    /**
     * 스트리밍 읽기. 첫 레코드가 헤더, 이후 레코드마다 헤더를 키로 하는 행을 콜백에 넘긴다. 헤더보다 짧은 행은 빈 문자열로 채운다.
     * 행을 보관하지 않으므로 큰 파일도 메모리에 다 올리지 않는다.
     */
    public static void forEachRow(Reader reader, Consumer<Map<String, String>> consumer) {
        try {
            scan(reader, new ArrayList<>(), consumer);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    public List<String> headers() {
        return headers;
    }

    public List<Map<String, String>> rows() {
        return rows;
    }

    private static void scan(Reader source, List<String> headersOut, Consumer<Map<String, String>> consumer) throws IOException {
        // 닫는 따옴표 판별에 한 글자 미리보기(mark/reset)가 필요하다. InputStreamReader 는 mark 를 지원하지 않으므로 감싼다.
        Reader reader = source.markSupported() ? source : new java.io.BufferedReader(source);
        List<String> fields = new ArrayList<>();
        StringBuilder field = new StringBuilder();
        boolean inQuotes = false;
        boolean fieldStarted = false;
        boolean first = true;
        boolean headerDone = false;

        int ch;
        while ((ch = reader.read()) >= 0) {
            char c = (char) ch;
            if (first) {
                first = false;
                if (c == '﻿') { // UTF-8 BOM
                    continue;
                }
            }
            if (inQuotes) {
                if (c == '"') {
                    // 이중 따옴표는 따옴표 하나, 그 외 닫는 따옴표
                    reader.mark(1);
                    int next = reader.read();
                    if (next == '"') {
                        field.append('"');
                    } else {
                        inQuotes = false;
                        if (next >= 0) {
                            reader.reset();
                        }
                    }
                } else {
                    field.append(c);
                }
                continue;
            }
            switch (c) {
                case '"' -> {
                    inQuotes = true;
                    fieldStarted = true;
                }
                case ',' -> {
                    fields.add(field.toString());
                    field.setLength(0);
                    fieldStarted = true;
                }
                case '\r' -> {
                    // CRLF 의 CR 은 무시한다
                }
                case '\n' -> {
                    if (fieldStarted || field.length() > 0) {
                        fields.add(field.toString());
                        headerDone = emit(fields, headersOut, headerDone, consumer);
                    }
                    fields = new ArrayList<>();
                    field.setLength(0);
                    fieldStarted = false;
                }
                default -> {
                    field.append(c);
                    fieldStarted = true;
                }
            }
        }
        if (fieldStarted || field.length() > 0) {
            fields.add(field.toString());
            emit(fields, headersOut, headerDone, consumer);
        }
    }

    /** 첫 레코드는 헤더로 삼고, 이후 레코드는 행으로 넘긴다. 헤더 처리 여부를 돌려준다. */
    private static boolean emit(List<String> record, List<String> headers, boolean headerDone, Consumer<Map<String, String>> consumer) {
        if (!headerDone) {
            record.stream().map(String::trim).forEach(headers::add);
            return true;
        }
        Map<String, String> row = new LinkedHashMap<>();
        for (int i = 0; i < headers.size(); i++) {
            row.put(headers.get(i), i < record.size() ? record.get(i) : "");
        }
        consumer.accept(row);
        return true;
    }
}
