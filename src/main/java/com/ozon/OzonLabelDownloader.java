package com.ozon;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Duration;

public class OzonLabelDownloader {

    private static final String BASE_URL = "https://api-seller.ozon.ru";
    private static final ObjectMapper MAPPER = new ObjectMapper();

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

    public static void main(String[] args) throws Exception {
        // 优先从命令行参数读取订单号，没有则从环境变量 POSTING_NUMBER 获取
        String postingNumber = (args.length > 0 && !args[0].isBlank()) 
                ? args[0].trim() 
                : System.getenv("POSTING_NUMBER");

        if (postingNumber == null || postingNumber.isBlank()) {
            System.err.println("错误：请提供待打印面单的订单号（货件号）！");
            System.exit(1);
        }

        if (CLIENT_ID.isEmpty() || API_KEY.isEmpty()) {
            System.err.println("错误：请检查 OZON_CLIENT_ID 和 OZON_API_KEY 环境变量！");
            System.exit(1);
        }

        System.out.println("=".repeat(70));
        System.out.printf("正在为货件号 [%s] 申请生成面单...\n", postingNumber);
        System.out.println("=".repeat(70));

        // 1. 发起生成面单任务
        ObjectNode createBody = MAPPER.createObjectNode();
        ArrayNode numbersArray = createBody.putArray("posting_number");
        numbersArray.add(postingNumber);

        HttpRequest createReq = HttpRequest.newBuilder()
                .uri(URI.create(BASE_URL + "/v2/posting/fbs/package-label"))
                .header("Client-Id", CLIENT_ID)
                .header("Api-Key", API_KEY)
                .header("Content-Type", "application/json")
                .timeout(Duration.ofSeconds(60))
                .POST(HttpRequest.BodyPublishers.ofString(createBody.toString()))
                .build();

        HttpResponse<String> createResp = HTTP_CLIENT.send(createReq, HttpResponse.BodyHandlers.ofString());
        if (createResp.statusCode() != 200) {
            System.err.printf("创建面单生成任务失败 (%d): %s\n", createResp.statusCode(), createResp.body());
            System.exit(1);
        }

        JsonNode createRoot = MAPPER.readTree(createResp.body());
        long taskId = createRoot.path("result").path("task_id").asLong();
        if (taskId == 0) {
            System.err.println("未获取到有效的 task_id: " + createResp.body());
            System.exit(1);
        }

        System.out.printf("✓ 面单任务已提交，Task ID: %d，正在等待官方渲染完成...\n", taskId);

        // 2. 轮询面单生成状态
        String pdfUrl = null;
        ObjectNode statusBody = MAPPER.createObjectNode();
        statusBody.put("task_id", taskId);

        for (int i = 1; i <= 15; i++) {
            Thread.sleep(2000);

            HttpRequest statusReq = HttpRequest.newBuilder()
                    .uri(URI.create(BASE_URL + "/v1/posting/fbs/package-label/status"))
                    .header("Client-Id", CLIENT_ID)
                    .header("Api-Key", API_KEY)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(statusBody.toString()))
                    .build();

            HttpResponse<String> statusResp = HTTP_CLIENT.send(statusReq, HttpResponse.BodyHandlers.ofString());
            if (statusResp.statusCode() == 200) {
                JsonNode statusRoot = MAPPER.readTree(statusResp.body());
                JsonNode result = statusRoot.path("result");
                String status = result.path("status").asText();

                System.out.printf("  - 检查状态 (%d/15): %s\n", i, status);

                if ("completed".equalsIgnoreCase(status)) {
                    pdfUrl = result.path("file_url").asText();
                    break;
                } else if ("failed".equalsIgnoreCase(status)) {
                    System.err.println("面单生成失败: " + result.path("error").asText());
                    System.exit(1);
                }
            }
        }

        if (pdfUrl == null || pdfUrl.isBlank()) {
            System.err.println("超时未能获取到面单下载链接！");
            System.exit(1);
        }

        System.out.println("✓ 面单生成成功！下载链接: " + pdfUrl);

        // 3. 下载 PDF 到本地磁盘
        String outputFileName = String.format("package_label_%s.pdf", postingNumber);
        HttpRequest downloadReq = HttpRequest.newBuilder()
                .uri(URI.create(pdfUrl))
                .GET()
                .build();

        HttpResponse<InputStream> downloadResp = HTTP_CLIENT.send(downloadReq, HttpResponse.BodyHandlers.ofInputStream());
        if (downloadResp.statusCode() == 200) {
            try (InputStream in = downloadResp.body()) {
                Files.copy(in, Path.of(outputFileName), StandardCopyOption.REPLACE_EXISTING);
            }
            System.out.printf("✓ 面单已成功下载保存至本地: %s\n", outputFileName);
        } else {
            System.err.printf("下载 PDF 失败，HTTP 状态码: %d\n", downloadResp.statusCode());
        }
    }
}
