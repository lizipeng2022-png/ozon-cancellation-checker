import os
import requests
import datetime
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

def run_simple_dump():
    now = datetime.datetime.now(datetime.timezone.utc)
    TOTAL_DAYS = 150
    STEP_DAYS = 15  # 每 15 天一段，回溯过去 150 天

    print("=" * 70)
    print(f"当前运行时间 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"【全量拉取】直接输出过去 {TOTAL_DAYS} 天内所有已取消订单")
    print("=" * 70)

    all_orders = {}
    all_initiators = set()

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
                "offset": offset
            }

            resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                print(f"区间 {since_str[:10]}~{to_str[:10]} 请求异常 ({resp.status_code}): {resp.text}")
                break

            data = resp.json()
            postings = data.get("postings") or data.get("result", {}).get("postings", [])
            if not postings:
                break

            print(f"✓ 区间 {since_str[:10]} ~ {to_str[:10]} (offset={offset}) 成功读取 {len(postings)} 笔取消订单")

            for item in postings:
                posting_num = item.get("posting_number")
                cancellation = item.get("cancellation", {})
                initiator = cancellation.get("cancellation_initiator")
                reason = cancellation.get("cancel_reason")
                reason_id = cancellation.get("cancel_reason_id")

                all_initiators.add(str(initiator))

                if posting_num not in all_orders:
                    all_orders[posting_num] = {
                        "posting_number": posting_num,
                        "initiator": initiator,
                        "reason": reason,
                        "reason_id": reason_id,
                        "in_process_at": item.get("in_process_at"),
                        "tracking_number": item.get("tracking_number")
                    }

            has_next = data.get("has_next") if "has_next" in data else data.get("result", {}).get("has_next", False)
            if not has_next:
                break
            offset += limit

    print("\n" + "=" * 70)
    print(f"【汇总统计】过去 {TOTAL_DAYS} 天共拉取到 {len(all_orders)} 笔不重复的已取消订单")
    print(f"【全部出现过的取消过失方 (cancellation_initiator)】：{list(all_initiators)}")
    print("=" * 70 + "\n")

    for idx, o in enumerate(all_orders.values(), 1):
        print(f"[{idx}] 货件号: {o['posting_number']} | 过失方: 【{o['initiator']}】 | 原因: {o['reason']} (ID: {o['reason_id']}) | 进单时间: {o['in_process_at']}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    run_simple_dump()
