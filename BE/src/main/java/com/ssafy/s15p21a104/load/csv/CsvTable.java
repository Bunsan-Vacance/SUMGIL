package com.ssafy.s15p21a104.load.csv;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 공공데이터 CSV 최소 파서. 헤더 1행, RFC 4180 따옴표 규칙, UTF-8 BOM·CRLF·빈 줄 허용.
 * 외부 의존성을 두지 않기 위해 직접 구현한다. 파일 크기가 작아(수백 행) 성능은 고려하지 않는다.
 */
public final class CsvTable {

    private final List<String> headers;
    private final List<Map<String, String>> rows;

    private CsvTable(List<String> headers, List<Map<String, String>> rows) {
        this.headers = List.copyOf(headers);
        this.rows = List.copyOf(rows);
    }

    public static CsvTable parse(String text) {
        List<List<String>> records = splitRecords(text.startsWith("\uFEFF") ? text.substring(1) : text);
        if (records.isEmpty()) {
            return new CsvTable(List.of(), List.of());
        }
        List<String> headers = records.get(0).stream().map(String::trim).toList();
        List<Map<String, String>> rows = new ArrayList<>();
        for (List<String> record : records.subList(1, records.size())) {
            Map<String, String> row = new LinkedHashMap<>();
            for (int i = 0; i < headers.size(); i++) {
                row.put(headers.get(i), i < record.size() ? record.get(i) : "");
            }
            rows.add(row);
        }
        return new CsvTable(headers, rows);
    }

    public List<String> headers() {
        return headers;
    }

    public List<Map<String, String>> rows() {
        return rows;
    }

    private static List<List<String>> splitRecords(String text) {
        List<List<String>> records = new ArrayList<>();
        List<String> fields = new ArrayList<>();
        StringBuilder field = new StringBuilder();
        boolean inQuotes = false;
        boolean fieldStarted = false;

        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (inQuotes) {
                if (c == '"') {
                    if (i + 1 < text.length() && text.charAt(i + 1) == '"') {
                        field.append('"');
                        i++;
                    } else {
                        inQuotes = false;
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
                        records.add(fields);
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
            records.add(fields);
        }
        return records;
    }
}
