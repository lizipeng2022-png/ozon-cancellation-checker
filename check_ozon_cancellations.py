import os
import requests
import datetime
import json
import sys

RAW_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
RAW_API_KEY = os.environ.get("OZON_API_KEY", "")

CLIENT_ID = "".join([c for c in RAW_CLIENT_ID if ord(c) < 128]).strip()
API_KEY = "".join([c for c in RAW_API_KEY if ord(c) < 128]).strip()

BASE_URL = "https://api-seller.ozon.ru"

headers = {
    "Client-Id": CLIENT_ID,
    "Api-Key": API_KEY,
    "Content-Type": "application/json"
}

def scan_orders():
    # 覆盖后台看到的 8 月密集进单区间
    since = "2026-07-20T00:00:00Z"
    to = "2026-08-30T23:59:59Z"

    print("=" * 70)
    print("【开始跨境订单接口联调探测】")
    print(f"查询区间: {since} 至 {to}")
    print("=" * 70)

    # 方案 1: 测试 /v3/posting/fbs/list 接口（跨境 realFBS 标准接口）
    print("\n▶ [测试 1] 正在请求 POST /v3/posting/fbs/list (状态: cancelled)...")
    payload_v3 = {
        "dir": "DESC",
        "filter": {
            "since": since,
            "to": to,
            "status": "cancelled"
        },
        "limit": 50,
        "offset": 0,
        "with": {
            "analytics_data": True,
            "financial_data": True
        }
    }
    resp_v3 = requests.post(f"{BASE_URL}/v3/posting/fbs/list", headers=headers, json=payload_v3, timeout=30)
    print(f"  └ 状态码: {resp_v3.status_code}")
    if resp_v3.status_code == 200:
        res = resp_v3.json().get("result", {})
        postings = res.get("postings", []) if isinstance(res, dict) else []
        print(f"  └ 成功获取到 {len(postings)} 笔订单！")
        if postings:
            print(f"    - 第一单号: {postings[0].get('posting_number')}")
            return
    else:
        print(f"  └ 响应内容: {resp_v3.text}")

    # 方案 2: 测试通用包裹检索接口 /v2/posting/fbs/list
    print("\n▶ [测试 2] 正在请求 POST /v2/posting/fbs/list ...")
    resp_v2 = requests.post(f"{BASE_URL}/v2/posting/fbs/list", headers=headers, json=payload_v3, timeout=30)
    print(f"  └ 状态码: {resp_v2.status_code}")
    if resp_v2.status_code == 200:
        postings = resp_v2.json().get("result", [])
        print(f"  └ 成功获取到 {len(postings)} 笔订单！")
        return
    else:
        print(f"  └ 响应内容: {resp_v2.text}")

    # 方案 3: 测试跨境全渠道列表 /v1/order/list
    print("\n▶ [测试 3] 正在请求 POST /v1/order/list ...")
    payload_v1 = {
        "dir": "desc",
        "filter": {
            "since": since,
            "to": to
        },
        "limit": 10
    }
    resp_order = requests.post(f"{BASE_URL}/v1/order/list", headers=headers, json=payload_v1, timeout=30)
    print(f"  └ 状态码: {resp_order.status_code}")
    if resp_order.status_code == 200:
        print(f"  └ 成功响应: {resp_order.json()}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    scan_orders()
