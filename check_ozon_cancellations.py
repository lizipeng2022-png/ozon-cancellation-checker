import os
import requests
import datetime
import json
import sys

# 从环境变量中读取
RAW_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
RAW_API_KEY = os.environ.get("OZON_API_KEY", "")
PUSHPLUS_TOKEN = (os.environ.get("PUSHPLUS_TOKEN") or "").strip()

INPUT_SINCE = os.environ.get("START_DATE")
INPUT_TO = os.environ.get("END_DATE")

# 强制过滤非 ASCII 字符与不可见空白，彻底解决 latin-1 编码报错
CLIENT_ID = "".join([c for c in RAW_CLIENT_ID if ord(c) < 128]).strip()
API_KEY = "".join([c for c in RAW_API_KEY if ord(c) < 128]).strip()

BASE_DOMAIN = "api-seller" + ".ozon.ru"
BASE_URL = f"https://{BASE_DOMAIN}"

def format_rfc3339(date_str, is_end=False):
    if not date_str:
        return None
    time_suffix = "23:59:59Z" if is_end else "00:00:00Z"
    return f"{date_str.strip()}T{time_suffix}"

def get_cancelled_postings():
    now = datetime.datetime.now(datetime.timezone.utc)
    default_since = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    default_to = now.strftime("%Y-%m-%dT23:59:59Z")

    since = format_rfc3339(INPUT_SINCE, False) or default_since
    to = format_rfc3339(INPUT_TO, True) or default_to

    print(f"正在查询时间范围: {since} 至 {to}")

    url = f"{BASE_URL}/v3/posting/fbs/list"
    headers = {
        "Client-Id": CLIENT_ID,
        "Api-Key": API_KEY,
        "Content-Type": "application/json"
    }

    claimable_orders = []
    offset = 0
    limit = 100

    LOGISTIC_KEYWORDS = ["доставка", "перевозчик", "утеря", "потер", "поврежд", "lost", "damage"]

    while True:
        payload = {
            "dir": "DESC",
            "filter": {
                "since": since,
                "to": to,
                "status": "cancelled"
            },
            "limit": limit,
            "offset": offset,
            "with": {
                "analytics_data": False,
                "financial_data": True
            }
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if resp.status_code != 200:
            print(f"Ozon API 请求失败，状态码: {resp.status_code}")
            print(f"错误响应: {resp.text}")
            sys.exit(1)

        data = resp.json()
        postings = data.get("result", {}).get("postings", [])
        if not postings:
            break

        for item in postings:
            cancellation = item.get("cancellation", {})
            initiator = (cancellation.get("cancellation_initiator") or "").lower()
            reason = cancellation.get("cancel_reason") or ""
            reason_lower = reason.lower()

            is_ozon_fault = False
            if initiator in ["ozon", "delivery", "logistic"]:
                is_ozon_fault = True
            elif any(kw in reason_lower for kw in LOGISTIC_KEYWORDS):
                is_ozon_fault = True

            if is_ozon_fault:
                claimable_orders.append({
                    "posting_number": item.get("posting_number"),
                    "cancel_reason": reason,
                    "initiator": initiator,
                    "cancel_date": cancellation.get("cancellation_after_analytics"),
                    "tracking_number": item.get("tracking_number"),
                    "price_total": sum(float(p.get("price", 0)) for p in item.get("products", []))
                })

        if not data.get("result", {}).get("has_next", False):
            break
        offset += limit

    return claimable_orders, since, to

def notify(orders, since, to):
    if not orders:
        print(f"\n[{since[:10]} ~ {to[:10]}] 时间段内未发现 Ozon/物流责任的取消订单。")
        return

    content_lines = [f"### 【Ozon索赔提醒】发现 {len(orders)} 笔责任取消订单\n"]
    content_lines.append(f"**查询周期**: `{since[:10]}` 至 `{to[:10]}`\n")
    for o in orders:
        line = (
            f"- **货件号**: `{o['posting_number']}`\n"
            f"  - 原因: {o['cancel_reason']} (发起方: {o['initiator']})\n"
            f"  - 金额: {o['price_total']}\n"
            f"  - 运单号: `{o['tracking_number']}`\n"
        )
        content_lines.append(line)

    markdown_body = "\n".join(content_lines)
    print("\n" + markdown_body)

    if PUSHPLUS_TOKEN:
        push_url = "http://www.pushplus.plus/send"
        payload = {
            "token": PUSHPLUS_TOKEN,
            "title": f"【Ozon索赔】{len(orders)}笔订单可申请赔偿",
            "content": markdown_body,
            "template": "markdown"
        }
        try:
            requests.post(push_url, json=payload, timeout=10)
        except Exception as e:
            print(f"PushPlus 推送异常: {e}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY 环境变量！")
    orders, s, t = get_cancelled_postings()
    notify(orders, s, t)
