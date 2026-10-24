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

def print_all_cancelled_orders():
    # 覆盖过去 150 天，确保完全覆盖 7月、8月、9月、10月的订单
    now = datetime.datetime.now(datetime.timezone.utc)
    since = (now - datetime.timedelta(days=150)).strftime("%Y-%m-%dT00:00:00Z")
    to = now.strftime("%Y-%m-%dT23:59:59Z")

    print("=" * 70)
    print(f"【全量取消订单探测】进单查询周期: {since[:10]} 至 {to[:10]}")
    print("=" * 70)

    offset = 0
    limit = 100
    all_postings = []

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

        all_postings.extend(postings)

        if not data.get("result", {}).get("has_next", False):
            break
        offset += limit

    print(f"\n成功获取到 {len(all_postings)} 笔已取消订单！\n")

    if not all_postings:
        print("未获取到任何订单，请检查 API Key 店铺权限。")
        return

    # 统计所有出现过的 initiator（过失方）和 cancel_reason（原因）
    initiators_set = set()
    reasons_set = set()

    print("=" * 70)
    print("【取消订单明细（观察拼写）】")
    print("=" * 70)
    for idx, item in enumerate(all_postings, 1):
        cancellation = item.get("cancellation", {})
        initiator = cancellation.get("cancellation_initiator")
        reason = cancellation.get("cancel_reason")
        reason_id = cancellation.get("cancel_reason_id")
        
        initiators_set.add(str(initiator))
        reasons_set.add(f"{reason} (ID: {reason_id})")

        print(f"[{idx}] 货件号: {item.get('posting_number')}")
        print(f"    - 取消过失方 (cancellation_initiator): 【{initiator}】")
        print(f"    - 取消原因 (cancel_reason): 【{reason}】 (ID: {reason_id})")
        print(f"    - 原始 cancellation: {cancellation}")

    print("\n" + "=" * 70)
    print("【归纳总结：所有出现过的过失方 (Initiators)】:")
    for init in initiators_set:
        print(f"  * {init}")

    print("\n【归纳总结：所有出现过的取消原因 (Cancel Reasons)】:")
    for r in reasons_set:
        print(f"  * {r}")
    print("=" * 70)

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    print_all_cancelled_orders()
