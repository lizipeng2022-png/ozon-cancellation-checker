import os
import requests
import datetime
import json
import sys

RAW_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
RAW_API_KEY = os.environ.get("OZON_API_KEY", "")
PUSHPLUS_TOKEN = (os.environ.get("PUSHPLUS_TOKEN") or "").strip()

CLIENT_ID = "".join([c for c in RAW_CLIENT_ID if ord(c) < 128]).strip()
API_KEY = "".join([c for c in RAW_API_KEY if ord(c) < 128]).strip()

BASE_URL = "https://api-seller.ozon.ru"

headers = {
    "Client-Id": CLIENT_ID,
    "Api-Key": API_KEY,
    "Content-Type": "application/json"
}

def is_client_or_seller(initiator_str):
    if not initiator_str:
        return False
    init = str(initiator_str).lower().strip()
    if any(k in init for k in ["клиент", "покупатель", "client", "buyer", "买家"]):
        return True
    if any(k in init for k in ["продавец", "seller", "卖家"]):
        return True
    return False

def run_checker():
    # 先对已知存在订单的 8月20日~8月26日 7天窗口做一次原始响应探测
    test_payload = {
        "dir": "DESC",
        "filter": {
            "since": "2026-08-20T00:00:00.000Z",
            "to": "2026-08-26T23:59:59.000Z",
            "status": "cancelled"
        },
        "limit": 100,
        "offset": 0,
        "with": {
            "analytics_data": True,
            "financial_data": True
        }
    }
    print("=" * 70)
    print("【精准7天窗口探测】2026-08-20 至 2026-08-26 (status=cancelled)")
    r_test = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=test_payload, timeout=30)
    print(f"HTTP 状态码: {r_test.status_code}")
    print(f"原始返回前500字符: {r_test.text[:500]}")
    print("=" * 70)

    # 动态按 7 天一个切片，扫描过去 150 天
    now = datetime.datetime.now(datetime.timezone.utc)
    TOTAL_DAYS = 150
    STEP_DAYS = 7

    matched_orders = {}
    all_cancelled_count = 0

    for day_start in range(0, TOTAL_DAYS, STEP_DAYS):
        t_to = now - datetime.timedelta(days=day_start)
        t_since = now - datetime.timedelta(days=min(day_start + STEP_DAYS, TOTAL_DAYS))

        since_str = t_since.strftime("%Y-%m-%dT00:00:00.000Z")
        to_str = t_to.strftime("%Y-%m-%dT23:59:59.000Z")

        offset = 0
        limit = 100

        while True:
            payload = {
                "dir": "DESC",
                "filter": {
                    "since": since_str,
                    "to": to_str,
                    "status": "cancelled"
                },
                "limit": limit,
                "offset": offset,
                "with": {
                    "financial_data": True
                }
            }

            resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                print(f"区间 {since_str[:10]}~{to_str[:10]} 异常 ({resp.status_code}): {resp.text}")
                break

            data = resp.json()
            postings = data.get("result", {}).get("postings", [])
            if not postings:
                break

            all_cancelled_count += len(postings)
            print(f"✓ 区间 {since_str[:10]} ~ {to_str[:10]} 抓取到 {len(postings)} 笔取消订单")

            for item in postings:
                cancellation = item.get("cancellation", {})
                initiator = cancellation.get("cancellation_initiator") or ""

                # 过滤买家和卖家责任
                if is_client_or_seller(initiator):
                    continue

                posting_num = item.get("posting_number")
                if posting_num not in matched_orders:
                    amount = sum(float(p.get("price", 0)) for p in item.get("products", []))
                    currency = item.get("products", [{}])[0].get("currency_code", "USD")
                    matched_orders[posting_num] = {
                        "posting_number": posting_num,
                        "initiator": initiator if initiator else "未标记(非买/卖家)",
                        "reason": cancellation.get("cancel_reason"),
                        "reason_id": cancellation.get("cancel_reason_id"),
                        "amount": f"{amount:.2f} {currency}",
                        "tracking_number": item.get("tracking_number"),
                        "in_process_at": item.get("in_process_at")
                    }

            if not data.get("result", {}).get("has_next", False):
                break
            offset += limit

    print("\n" + "=" * 70)
    print(f"【扫描汇总】过去 150 天共拉取到 {all_cancelled_count} 笔已取消订单")
    print(f"【索赔符合】其中非买/卖家责任（可索赔）共 {len(matched_orders)} 笔：")
    print("=" * 70)

    for idx, o in enumerate(matched_orders.values(), 1):
        print(f"[{idx}] 货件号: {o['posting_number']}")
        print(f"    - 取消过失方: {o['initiator']}")
        print(f"    - 取消原因: {o['reason']} (ID: {o['reason_id']})")
        print(f"    - 订单金额: {o['amount']} | 运单号: {o['tracking_number']}")
        print(f"    - 进单时间: {o['in_process_at']}\n")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    run_checker()
