package com.ssafy.s15p21a104.collect.http;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * JDK {@link HttpClient} 기반 {@link HttpFetcher}. 연결 한계는 클라이언트에, 응답 한계는 요청마다 건다.
 * 인증키는 예외 메시지에서 {@code {KEY}} 로 가린다 (쿼리로 들어가는 키는 URL 인코딩된 형태도 함께).
 */
public final class JdkHttpFetcher implements HttpFetcher {

    private final HttpClient client;
    private final Duration readTimeout;
    private final String secret;

    /** @param secret 로그·메시지에서 가릴 문자열(인증키). null 이면 가리지 않는다 */
    public JdkHttpFetcher(HttpClient client, Duration readTimeout, String secret) {
        this.client = client;
        this.readTimeout = readTimeout;
        this.secret = secret;
    }

    @Override
    public String get(URI uri) {
        String redacted = redact(uri.toString(), secret);
        HttpRequest request = HttpRequest.newBuilder(uri)
                .timeout(readTimeout)
                .header("Accept", "application/json")
                .header("User-Agent", "sumgil-collector")
                .GET()
                .build();
        try {
            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            int status = response.statusCode();
            if (status >= 400) {
                throw SourceCallException.http(redacted, status);
            }
            return response.body();
        } catch (HttpTimeoutException e) {
            throw SourceCallException.timeout(redacted, e);
        } catch (IOException e) {
            throw SourceCallException.io(redacted, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new SourceCallException(SourceCallException.Kind.HTTP_4XX, "호출 중 인터럽트: " + redacted, null, null, e);
        }
    }

    public static String redact(String text, String secret) {
        if (secret == null || secret.isBlank() || text == null) {
            return text;
        }
        String out = text.replace(secret, "{KEY}");
        return out.replace(URLEncoder.encode(secret, StandardCharsets.UTF_8), "{KEY}");
    }
}
