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

def scan_raw_orders():
    # 锁定后台明确有大量订单的 8 月进单区间
    since = "2026-08-01T00:00:00Z"
    to = "2026-08-28T23:59:59Z"

    print("=" * 70)
    print(f"【最简全量探测】查询区间: {since[:10]} 至 {to[:10]}")
    print("=" * 70)

    # 1. 先验证反查已知单号，确保通信与权限百分之百正常
    sample_posting = "62662023-0335-1"
    print(f"\n[第1步] 正在用 /v3/posting/fbs/get 确认单号 {sample_posting} ...")
    r1 = requests.post(
        f"{BASE_URL}/v3/posting/fbs/get",
        headers=headers,
        json={"posting_number": sample_posting, "with": {"analytics_data": True, "financial_data": True}},
        timeout=30
    )
    if r1.status_code == 200:
        res = r1.json().get("result", {})
        print(f"  ✓ 成功读取单号: {res.get('posting_number')}")
        print(f"  ✓ 真实状态 status: {res.get('status')}")
        print(f"  ✓ cancellation 节点: {res.get('cancellation')}")
    else:
        print(f"  ✗ 单号反查失败: {r1.status_code}, {r1.text}")

    # 2. 测试跨境 realFBS 列表接口：不带 status 过滤
    print(f"\n[第2步] 正在用 /v4/posting/fbs/list 拉取全量订单列表 (无状态限制)...")
    payload = {
        "dir": "DESC",
        "filter": {
            "since": since,
            "to": to
        },
        "limit": 50,
        "offset": 0
    }
    r2 = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
    print(f"  - HTTP 响应码: {r2.status_code}")
    data = r2.json()
    postings = data.get("result", {}).get("postings", [])
    print(f"  - 获取到订单数量: {len(postings)}")

    if not postings:
        # 如果 /v4 确实对 crossborder 订单返回空，尝试 Ozon 跨境专用未完成列表
        print(f"\n[第3步] 尝试请求 /v3/posting/fbs/unfulfilled/list (跨境常用未结接口)...")
        r3 = requests.post(f"{BASE_URL}/v3/posting/fbs/unfulfilled/list", headers=headers, json={"dir": "DESC", "limit": 50, "offset": 0}, timeout=30)
        print(f"  - HTTP 响应码: {r3.status_code}")
        if r3.status_code == 200:
            unf = r3.json().get("result", {}).get("postings", [])
            print(f"  - 获取到订单数: {len(unf)}")

    # 3. 打印拿到的所有订单基本信息
    if postings:
        print("\n" + "=" * 70)
        print(f"【成功拉取到 {len(postings)} 笔订单明细】:")
        print("=" * 70)
        for idx, item in enumerate(postings, 1):
            canc = item.get("cancellation", {})
            print(f"[{idx}] 货件号: {item.get('posting_number')} | 状态: {item.get('status')}")
            if canc:
                print(f"    - 取消过失方: {canc.get('cancellation_initiator')}")
                print(f"    - 取消原因: {canc.get('cancel_reason')}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    scan_raw_orders()
