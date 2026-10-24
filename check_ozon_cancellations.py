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
    STEP_DAYS = 30  # 每 30 天一段，共 5 段即可覆盖 150 天

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

        cursor = ""
        limit = 100
        page = 1

        while True:
            payload = {
                "dir": "DESC",
                "filter": {
                    "since": since_str,
                    "to": to_str,
                    "status": "cancelled"
                },
                "limit": limit
            }
            # v4 接口使用 cursor 翻页
            if cursor:
                payload["cursor"] = cursor

            resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                print(f"区间 {since_str[:10]}~{to_str[:10]} 请求异常 ({resp.status_code}): {resp.text}")
                break

            data = resp.json()
            postings = data.get("postings") or data.get("result", {}).get("postings", [])
            if not postings:
                break

            new_count = 0
            for item in postings:
                posting_num = item.get("posting_number")
                cancellation = item.get("cancellation", {})
                initiator = cancellation.get("cancellation_initiator")
                reason = cancellation.get("cancel_reason")
                reason_id = cancellation.get("cancel_reason_id")

                all_initiators.add(str(initiator))

                if posting_num not in all_orders:
                    new_count += 1
                    all_orders[posting_num] = {
                        "posting_number": posting_num,
                        "initiator": initiator,
                        "reason": reason,
                        "reason_id": reason_id,
                        "in_process_at": item.get("in_process_at"),
                        "tracking_number": item.get("tracking_number")
                    }

            print(f"✓ 区间 {since_str[:10]} ~ {to_str[:10]} (第{page}页) 读取 {len(postings)} 笔，新增不重复 {new_count} 笔")

            # 防死循环保护：如果本页全是已读过的重复订单，说明游标未生效或已到底，直接跳出
            if new_count == 0:
                break

            has_next = data.get("has_next", False)
            next_cursor = data.get("cursor", "")
            if not has_next or not next_cursor or next_cursor == cursor:
                break

            cursor = next_cursor
            page += 1

    print("\n" + "=" * 70)
    print(f"【汇总统计】过去 {TOTAL_DAYS} 天共拉取到 {len(all_orders)} 笔不重复的已取消订单")
    print(f"【全部出现过的取消过失方 (cancellation_initiator)】：{list(all_initiators)}")
    print("=" * 70 + "\n")

    for idx, o in enumerate(all_orders.values(), 1):
        print(f"[{idx}] 货件号: {o['posting_number']} | 过失方: 【{o['initiator']}】 | 原因: {o['reason']} (ID: {o['reason_id']}) | 进单时间: {o['in_process_at']}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    run_simple_dump()import os
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
    STEP_DAYS = 30  # 每 30 天一段，共 5 段即可覆盖 150 天

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

        cursor = ""
        limit = 100
        page = 1

        while True:
            payload = {
                "dir": "DESC",
                "filter": {
                    "since": since_str,
                    "to": to_str,
                    "status": "cancelled"
                },
                "limit": limit
            }
            # v4 接口使用 cursor 翻页
            if cursor:
                payload["cursor"] = cursor

            resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                print(f"区间 {since_str[:10]}~{to_str[:10]} 请求异常 ({resp.status_code}): {resp.text}")
                break

            data = resp.json()
            postings = data.get("postings") or data.get("result", {}).get("postings", [])
            if not postings:
                break

            new_count = 0
            for item in postings:
                posting_num = item.get("posting_number")
                cancellation = item.get("cancellation", {})
                initiator = cancellation.get("cancellation_initiator")
                reason = cancellation.get("cancel_reason")
                reason_id = cancellation.get("cancel_reason_id")

                all_initiators.add(str(initiator))

                if posting_num not in all_orders:
                    new_count += 1
                    all_orders[posting_num] = {
                        "posting_number": posting_num,
                        "initiator": initiator,
                        "reason": reason,
                        "reason_id": reason_id,
                        "in_process_at": item.get("in_process_at"),
                        "tracking_number": item.get("tracking_number")
                    }

            print(f"✓ 区间 {since_str[:10]} ~ {to_str[:10]} (第{page}页) 读取 {len(postings)} 笔，新增不重复 {new_count} 笔")

            # 防死循环保护：如果本页全是已读过的重复订单，说明游标未生效或已到底，直接跳出
            if new_count == 0:
                break

            has_next = data.get("has_next", False)
            next_cursor = data.get("cursor", "")
            if not has_next or not next_cursor or next_cursor == cursor:
                break

            cursor = next_cursor
            page += 1

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
