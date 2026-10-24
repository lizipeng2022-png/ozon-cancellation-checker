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

def fetch_cancelled_orders():
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # 将过去 150 天按每 30 天切分为一个窗口，避免 Ozon API 超出单次时间跨度限制
    CHUNK_DAYS = 30
    TOTAL_DAYS = 150
    
    all_cancelled = []

    print("=" * 70)
    print(f"开始分段扫描过去 150 天内的所有已取消订单（当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC）")
    print("=" * 70)

    for day_start in range(0, TOTAL_DAYS, CHUNK_DAYS):
        t_to = now - datetime.timedelta(days=day_start)
        t_since = now - datetime.timedelta(days=min(day_start + CHUNK_DAYS, TOTAL_DAYS))
        
        since_str = t_since.strftime("%Y-%m-%dT00:00:00Z")
        to_str = t_to.strftime("%Y-%m-%dT23:59:59Z")
        
        print(f"\n▶ 正在扫描时间段: {since_str[:10]} 至 {to_str[:10]} ...")
        
        offset = 0
        limit = 50
        chunk_orders = []

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
                    "analytics_data": False,
                    "financial_data": True
                }
            }

            resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                print(f"请求失败 ({resp.status_code}): {resp.text}")
                break

            data = resp.json()
            postings = data.get("result", {}).get("postings", [])
            if not postings:
                break

            chunk_orders.extend(postings)
            
            if not data.get("result", {}).get("has_next", False):
                break
            offset += limit

        print(f"  └ 该区间获取到 {len(chunk_orders)} 笔取消订单")
        all_cancelled.extend(chunk_orders)

    print("\n" + "=" * 70)
    print(f"【全量输出】过去 150 天共累计获取到 {len(all_cancelled)} 笔已取消订单：")
    print("=" * 70)

    if not all_cancelled:
        print("未获取到任何订单。请务必检查：GitHub Secrets 中的 Client-Id / Api-Key 绑定的店铺是否为当前的【Модная Волна】。")
        return

    for idx, item in enumerate(all_cancelled, 1):
        cancellation = item.get("cancellation", {})
        initiator = cancellation.get("cancellation_initiator")
        reason = cancellation.get("cancel_reason")
        posting_num = item.get("posting_number")
        
        print(f"[{idx}] 货件号: {posting_num}")
        print(f"    - 取消过失方: {initiator}")
        print(f"    - 取消原因: {reason}")
        print(f"    - 下单时间 (in_process_at): {item.get('in_process_at')}")
        print(f"    - 运单号: {item.get('tracking_number')}\n")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY 环境变量！")
    fetch_cancelled_orders()
