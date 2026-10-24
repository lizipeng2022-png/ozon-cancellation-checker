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

def scan_all_postings():
    # 按照后台页面能明确看到大量订单的区间：2026-08-01 至 2026-08-26
    since = "2026-08-01T00:00:00Z"
    to = "2026-08-26T23:59:59Z"

    print("=" * 70)
    print(f"【全量订单无状态扫描】进单时间范围: {since} 至 {to}")
    print("【测试目的】去掉 status: cancelled，查看 API 返回的真实状态与取消信息")
    print("=" * 70)

    offset = 0
    limit = 50
    total_postings = []

    while True:
        # 去掉 status 过滤条件，全量拉取
        payload = {
            "dir": "DESC",
            "filter": {
                "since": since,
                "to": to
            },
            "limit": limit,
            "offset": offset,
            "with": {
                "analytics_data": True,
                "financial_data": True
            }
        }

        resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"Ozon API 请求失败: {resp.status_code}, {resp.text}")
            sys.exit(1)

        data = resp.json()
        postings = data.get("result", {}).get("postings", [])
        if not postings:
            break

        total_postings.extend(postings)

        # 仅测试前 100 笔订单即可看到规律
        if len(total_postings) >= 100 or not data.get("result", {}).get("has_next", False):
            break
        offset += limit

    print(f"\n【扫描统计】共成功拉取到 {len(total_postings)} 笔订单！\n")

    if not total_postings:
        print("依然拉取到 0 笔订单。请检查 Client-Id/Api-Key 是否对应当前查看的店铺。")
        return

    # 统计所有订单的状态分布
    status_summary = {}
    cancelled_orders = []

    for item in total_postings:
        st = item.get("status")
        status_summary[st] = status_summary.get(st, 0) + 1
        
        # 只要带有 cancellation 或者是 cancelled 状态就记录
        if st == "cancelled" or item.get("cancellation"):
            cancelled_orders.append(item)

    print("=" * 70)
    print("【当前拉取到的所有订单状态分布统计】:")
    for st, count in status_summary.items():
        print(f"  * 状态 [{st}]: {count} 笔")
    print("=" * 70)

    print(f"\n【其中已取消或含取消信息的订单共有 {len(cancelled_orders)} 笔】：\n")
    for idx, item in enumerate(cancelled_orders, 1):
        cancellation = item.get("cancellation", {})
        print(f"[{idx}] 货件号: {item.get('posting_number')} (状态: {item.get('status')})")
        print(f"    - 取消过失方 (cancellation_initiator): 【{cancellation.get('cancellation_initiator')}】")
        print(f"    - 取消原因 (cancel_reason): 【{cancellation.get('cancel_reason')}】 (ID: {cancellation.get('cancel_reason_id')})")
        print(f"    - 取消类型 (cancellation_type): {cancellation.get('cancellation_type')}")
        print(f"    - 原始 cancellation 节点: {cancellation}\n")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    scan_all_postings()
