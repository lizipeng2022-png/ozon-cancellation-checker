import os
import requests
import datetime
import json
import sys

RAW_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
RAW_API_KEY = os.environ.get("OZON_API_KEY", "")

CLIENT_ID = "".join([c for c in RAW_CLIENT_ID if ord(c) < 128]).strip()
API_KEY = "".join([c for c in RAW_API_KEY if ord(c) < 128]).strip()

BASE_DOMAIN = "api-seller" + ".ozon.ru"
BASE_URL = f"https://{BASE_DOMAIN}"

def parse_iso_time(time_str):
    """解析 RFC3339 / ISO 时间字符串为 UTC datetime"""
    if not time_str:
        return None
    time_str = time_str.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(time_str)
    except Exception:
        return None

def get_claimable_orders():
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # 索赔合格区间：取消距今 60 ~ 90 天
    target_cancel_end = now - datetime.timedelta(days=60)
    target_cancel_start = now - datetime.timedelta(days=90)

    # 为了确保不漏掉这批订单，API 拉取过去 150 天内的订单
    api_since = (now - datetime.timedelta(days=150)).strftime("%Y-%m-%dT00:00:00Z")
    api_to = now.strftime("%Y-%m-%dT23:59:59Z")

    print("=" * 60)
    print(f"当前时间 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"【目标取消日期区间】: {target_cancel_start.strftime('%Y-%m-%d')} 至 {target_cancel_end.strftime('%Y-%m-%d')} (满60天且<90天)")
    print(f"【API拉取订单生成周期】: {api_since[:10]} 至 {api_to[:10]}")
    print("=" * 60)

    url = f"{BASE_URL}/v4/posting/fbs/list"
    headers = {
        "Client-Id": CLIENT_ID,
        "Api-Key": API_KEY,
        "Content-Type": "application/json"
    }

    offset = 0
    limit = 100
    matched_orders = []

    # 官方/承运商责任关键词
    LOGISTIC_KEYWORDS = ["доставка", "перевозчик", "утеря", "потер", "поврежд", "lost", "damage"]
    CLIENT_KEYWORDS = ["клиент", "покупатель", "передумал", "не подош", "client", "buyer"]

    while True:
        payload = {
            "dir": "DESC",
            "filter": {
                "since": api_since,
                "to": api_to,
                "status": "cancelled"
            },
            "limit": limit,
            "offset": offset,
            "with": {
                "analytics_data": True,
                "financial_data": True
            }
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"Ozon API 请求失败: {resp.status_code}, {resp.text}")
            sys.exit(1)

        data = resp.json()
        postings = data.get("result", {}).get("postings", [])
        if not postings:
            break

        for item in postings:
            cancellation = item.get("cancellation", {})
            initiator = (cancellation.get("cancellation_initiator") or "").lower().strip()
            reason = cancellation.get("cancel_reason") or ""
            reason_lower = reason.lower().strip()

            # 1. 提取取消时间 (以 cancellation 节点或 analytics 为准)
            cancel_time_str = cancellation.get("cancellation_after_analytics") or item.get("in_process_at")
            cancel_time = parse_iso_time(cancel_time_str)

            if not cancel_time:
                continue

            # 2. 判断取消时间是否落在 60 ~ 90 天窗口内
            days_since_cancel = (now - cancel_time).days
            if not (60 <= days_since_cancel <= 90):
                continue

            # 3. 责任方判断：排除买家/卖家责任
            if initiator in CLIENT_KEYWORDS or any(kw in reason_lower for kw in CLIENT_KEYWORDS):
                continue
            if initiator == "seller":
                continue

            # 判断是否符合 Ozon 赔付
            is_ozon_fault = False
            if initiator in ["ozon", "delivery", "logistic", "carrier"]:
                is_ozon_fault = True
            elif any(kw in reason_lower for kw in LOGISTIC_KEYWORDS):
                is_ozon_fault = True

            if is_ozon_fault:
                matched_orders.append({
                    "posting_number": item.get("posting_number"),
                    "cancel_date": cancel_time.strftime("%Y-%m-%d %H:%M"),
                    "days_ago": days_since_cancel,
                    "reason": reason,
                    "initiator": initiator,
                    "tracking_number": item.get("tracking_number"),
                    "amount": sum(float(p.get("price", 0)) for p in item.get("products", []))
                })

        if not data.get("result", {}).get("has_next", False):
            break
        offset += limit

    # 输出结果
    print(f"\n【筛查结果】共发现 {len(matched_orders)} 笔符合“取消满60天且未满90天”的 Ozon 责任订单：\n")
    for o in matched_orders:
        print(f"▶ 货件号: {o['posting_number']}")
        print(f"  - 取消时间: {o['cancel_date']} (已取消 {o['days_ago']} 天)")
        print(f"  - 取消原因: {o['reason']} [发起方: {o['initiator']}]")
        print(f"  - 货件金额: {o['amount']} | 运单号: {o['tracking_number']}\n")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    get_claimable_orders()
