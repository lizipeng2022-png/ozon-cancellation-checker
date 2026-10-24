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

def get_all_cancelled_orders():
    now = datetime.datetime.now(datetime.timezone.utc)
    # 拉取过去 150 天内生成的订单
    api_since = (now - datetime.timedelta(days=150)).strftime("%Y-%m-%dT00:00:00Z")
    api_to = now.strftime("%Y-%m-%dT23:59:59Z")

    print("=" * 60)
    print(f"当前时间 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"【API拉取周期（过去150天）】: {api_since} 至 {api_to}")
    print("=" * 60)

    url = f"{BASE_URL}/v4/posting/fbs/list"
    headers = {
        "Client-Id": CLIENT_ID,
        "Api-Key": API_KEY,
        "Content-Type": "application/json"
    }

    offset = 0
    limit = 100
    all_postings = []

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

        all_postings.extend(postings)

        if not data.get("result", {}).get("has_next", False):
            break
        offset += limit

    print(f"\n【接口响应统计】过去 150 天共成功拉取到 {len(all_postings)} 笔已取消订单！\n")

    if not all_postings:
        print("未获取到任何订单。请检查 Client-Id/Api-Key 对应店铺是否有对应时间段的 FBS 订单。")
        return

    # 打印前 1 个订单的完整 JSON 报文样本，供核对字段名
    print("=" * 60)
    print("【第一笔订单完整 JSON 报文示例】:")
    print(json.dumps(all_postings[0], indent=2, ensure_ascii=False))
    print("=" * 60)

    # 依次打印所有订单的货件号、取消详情及时间字段
    print("\n【全部已取消订单明细清单】:")
    for idx, item in enumerate(all_postings, 1):
        cancellation = item.get("cancellation", {})
        print(f"\n[{idx}] 货件号: {item.get('posting_number')}")
        print(f"  - 运单号: {item.get('tracking_number')}")
        print(f"  - 进单时间 (in_process_at): {item.get('in_process_at')}")
        print(f"  - 取消原因: {cancellation.get('cancel_reason')} (ID: {cancellation.get('cancel_reason_id')})")
        print(f"  - 取消发起方: {cancellation.get('cancellation_initiator')}")
        print(f"  - cancellation 完整字典: {cancellation}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    get_all_cancelled_orders()
