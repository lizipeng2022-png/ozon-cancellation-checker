package com.ozon;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.*;

public class OzonCancellationChecker {

    private static final String BASE_URL = "https://api-seller.ozon.ru";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    // 仅保留 Ozon 核心凭据
    private static final String CLIENT_ID = sanitize(System.getenv("OZON_CLIENT_ID"));
    private static final String API_KEY = sanitize(System.getenv("OZON_API_KEY"));

    private static final HttpClient HTTP_CLIENT = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(30))
            .build();

    private static String sanitize(String str) {
        if (str == null) return "";
        StringBuilder sb = new StringBuilder();
        for (char c : str.toCharArray()) {
            if (c < 128) sb.append(c);
        }
        return sb.toString().trim();
    }

    public static void main(String[] args) {
        if (CLIENT_ID.isEmpty() || API_KEY.isEmpty()) {
            System.err.println("错误：请检查 OZON_CLIENT_ID 和 OZON_API_KEY 环境变量！");
            System.exit(1);
        }
        filterClaimableOrders();
    }

    private static boolean isClientOrSeller(String initiator) {
        if (initiator == null) return false;
        String init = initiator.trim();
        return "Клиент".equals(init) || "Продавец".equals(init);
    }

    private static Instant parseIsoInstant(String isoStr) {
        if (isoStr == null || isoStr.isBlank()) return null;
        try {
            return Instant.parse(isoStr);
        } catch (Exception e) {
            return null;
        }
    }

    private static JsonNode safePost(String url, String jsonBody, int maxAttempts) {
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                HttpRequest request = HttpRequest.newBuilder()
                        .uri(URI.create(url))
                        .header("Client-Id", CLIENT_ID)
                        .header("Api-Key", API_KEY)
                        .header("Content-Type", "application/json")
                        .timeout(Duration.ofSeconds(60))
                        .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                        .build();

                HttpResponse<String> response = HTTP_CLIENT.send(request, HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() == 200) {
                    return MAPPER.readTree(response.body());
                } else if (response.statusCode() >= 500) {
                    System.out.printf("  [网络提示] Ozon 返回错误 (%d)，正在进行第 %d/%d 次重试...\n", response.statusCode(), attempt, maxAttempts);
                } else {
                    System.out.printf("API 请求失败 (%d): %s\n", response.statusCode(), response.body());
                    return null;
                }
            } catch (Exception e) {
                System.out.printf("  [网络提示] 连接超时或握手异常 (%s)，正在第 %d/%d 次重试...\n", e.getClass().getSimpleName(), attempt, maxAttempts);
            }
            try {
                Thread.sleep(3000);
            } catch (InterruptedException ignored) {}
        }
        return null;
    }

    public static void filterClaimableOrders() {
        Instant now = Instant.now();
        int totalDays = 150;
        int stepDays = 30;

        System.out.println("=".repeat(80));
        System.out.println("当前运行时间 (UTC): " + now.toString());
        System.out.println("【索赔目标窗口】取消满 60 天 且 未超过 90 天 (60 <= 取消天数 <= 90)");
        System.out.println("【过滤规则】1. 必须是真实取消订单 (status == 'cancelled')");
        System.out.println("            2. 排除买家('Клиент')与卖家('Продавец')");
        System.out.println("            3. 取消时间严格落在 60~90 天窗口内");
        System.out.println("=".repeat(80));

        Map<String, OrderClaimInfo> matchedOrders = new LinkedHashMap<>();
        int totalCancelledScanned = 0;
        int nonClientSellerCount = 0;

        for (int dayStart = 0; dayStart < totalDays; dayStart += stepDays) {
            Instant tTo = now.minus(dayStart, ChronoUnit.DAYS);
            Instant tSince = now.minus(Math.min(dayStart + stepDays, totalDays), ChronoUnit.DAYS);

            String sinceStr = tSince.toString();
            String toStr = tTo.toString();

            String cursor = "";
            int limit = 100;

            while (true) {
                ObjectNode payloadNode = MAPPER.createObjectNode();
                payloadNode.put("dir", "DESC");
                payloadNode.put("limit", limit);

                ObjectNode filterNode = payloadNode.putObject("filter");
                filterNode.put("since", sinceStr);
                filterNode.put("to", toStr);
                filterNode.put("status", "cancelled");

                if (!cursor.isEmpty()) {
                    payloadNode.put("cursor", cursor);
                }

                JsonNode root = safePost(BASE_URL + "/v4/posting/fbs/list", payloadNode.toString(), 3);
                if (root == null) break;

                JsonNode postings = root.has("postings") ? root.get("postings") : root.path("result").path("postings");
                if (postings == null || !postings.isArray() || postings.isEmpty()) {
                    break;
                }

                for (JsonNode item : postings) {
                    if (!"cancelled".equalsIgnoreCase(item.path("status").asText())) {
                        continue;
                    }
                    totalCancelledScanned++;

                    JsonNode canc = item.path("cancellation");
                    String initiator = canc.path("cancellation_initiator").asText(null);

                    if (isClientOrSeller(initiator)) {
                        continue;
                    }
                    nonClientSellerCount++;

                    String postingNum = item.path("posting_number").asText();

                    String cancelTimeRaw = canc.hasNonNull("cancellation_date") ? canc.path("cancellation_date").asText() :
                            (item.hasNonNull("delivering_date") ? item.path("delivering_date").asText() : item.path("in_process_at").asText(null));

                    Instant cancelDt = parseIsoInstant(cancelTimeRaw);
                    long daysSinceCancel = cancelDt != null ? ChronoUnit.DAYS.between(cancelDt, now) : -1;

                    // 60 <= 取消天数 <= 90
                    if (daysSinceCancel < 60 || daysSinceCancel > 90) {
                        continue;
                    }

                    if (!matchedOrders.containsKey(postingNum)) {
                        matchedOrders.put(postingNum, new OrderClaimInfo(
                                postingNum,
                                initiator != null ? initiator : "未填写",
                                canc.path("cancel_reason").asText(""),
                                canc.path("cancel_reason_id").asLong(0),
                                cancelTimeRaw,
                                daysSinceCancel,
                                item.path("in_process_at").asText(""),
                                item.path("tracking_number").asText("")
                        ));
                    }
                }

                boolean hasNext = root.path("has_next").asBoolean(root.path("result").path("has_next").asBoolean(false));
                String nextCursor = root.path("cursor").asText("");

                if (!hasNext || nextCursor.isEmpty() || nextCursor.equals(cursor)) {
                    break;
                }
                cursor = nextCursor;
            }
        }

        System.out.println("\n" + "=".repeat(80));
        System.out.printf("【扫描汇总】总取消单: %d 笔 | 非买/卖家责任: %d 笔\n", totalCancelledScanned, nonClientSellerCount);
        System.out.printf("【索赔窗口命中】刚好取消满 60~90 天的可直接索赔订单: %d 笔\n", matchedOrders.size());
        System.out.println("=".repeat(80) + "\n");

        int idx = 1;
        for (OrderClaimInfo o : matchedOrders.values()) {
            System.out.printf("[%d] 货件号: %s\n", idx++, o.postingNumber);
            System.out.printf("    - 取消过失方: 【%s】\n", o.initiator);
            System.out.printf("    - 取消原因: 【%s】 (ID: %d)\n", o.reason, o.reasonId);
            System.out.printf("    - 取消时间: %s (已取消 %d 天，处于 60~90 天索赔期)\n", o.cancelTime, o.daysSinceCancel);
            System.out.printf("    - 运单号: %s\n\n", o.trackingNumber);
        }
    }

    private record OrderClaimInfo(
            String postingNumber,
            String initiator,
            String reason,
            long reasonId,
            String cancelTime,
            long daysSinceCancel,
            String inProcessAt,
            String trackingNumber
    ) {}
}
