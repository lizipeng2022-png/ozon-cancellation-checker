import os
import requests
import datetime
import json
import sys

# 从环境变量中读取
RAW_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
RAW_API_KEY = os.environ.get("OZON_API_KEY", "")

INPUT_SINCE = os.environ.get("START_DATE")
INPUT_TO = os.environ.get("END_DATE")

# 清洗凭据
CLIENT_ID = "".join([c for c in RAW_CLIENT_ID if ord(c) < 128]).strip()
API_KEY = "".join([c for c in RAW_API_KEY if ord(c) < 128]).strip()

BASE_DOMAIN = "api-seller" + ".ozon.ru"
BASE_URL = f"https://{BASE_DOMAIN}"

def format_rfc3339(date_str, is_end=False):
    if not date_str:
        return None
    time_suffix = "23:59:59Z" if is_end else "00:00:00Z"
    return f"{date_str.strip()}T{time_suffix}"

def dump_all_cancelled_postings():
    now = datetime.datetime.now(datetime.timezone.utc)
    default_since = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    default_to = now.strftime("%Y-%m-%dT23:59:59Z")

    since = format_rfc3339(INPUT_SINCE, False) or default_since
    to = format_rfc3339(INPUT_TO, True) or default_to

    print("=" * 60)
    print(f"【开始拉取全量取消订单】时间范围: {since} 至 {to}")
    print("=" * 60)

    url = f"{BASE_URL}/v4/posting/fbs/list"
    headers = {
        "Client-Id": CLIENT_ID,
        "Api-Key": API_KEY,
        "Content-Type": "application/json"
    }

    offset = 0
    limit = 100
    total_postings = []

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

        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if resp.status_code != 200:
            print(f"Ozon API 请求失败，状态码: {resp.status_code}")
            print(f"错误响应: {resp.text}")
            sys.exit(1)

        data = resp.json()
        postings = data.get("result", {}).get("postings", [])
        if not postings:
            break

        total_postings.extend(postings)

        if not data.get("result", {}).get("has_next", False):
            break
        offset += limit

    print(f"\n查询完成！该时间段内共获取到 {len(total_postings)} 笔取消订单。\n")

    if not total_postings:
        print("未查询到任何已取消订单。如果该时间段确实有订单被取消，请确认后台订单创建时间是否在该范围内。")
        return

    # 1. 打印第一个订单的完整 JSON 报文样本，供结构分析
    print("=" * 60)
    print("【样本订单完整 JSON 报文结构】:")
    print(json.dumps(total_postings[0], indent=2, ensure_ascii=False))
    print("=" * 60)

    # 2. 依次输出每一笔取消订单的核心责任关键字段
    print("\n【所有取消订单明细清单】:")
    for idx, item in enumerate(total_postings, 1):
        cancellation = item.get("cancellation", {})
        print(f"\n[{idx}] 货件号: {item.get('posting_number')}")
        print(f"    - 发起方 (cancellation_initiator): {cancellation.get('cancellation_initiator')}")
        print(f"    - 取消原因 (cancel_reason): {cancellation.get('cancel_reason')}")
        print(f"    - 取消原因 ID (cancel_reason_id): {cancellation.get('cancel_reason_id')}")
        print(f"    - 取消类型 (cancellation_type): {cancellation.get('cancellation_type')}")
        print(f"    - 运单号 (tracking_number): {item.get('tracking_number')}")
        print(f"    - 货件当前状态 (status): {item.get('status')}")
        print(f"    - 取消详情节点 (cancellation raw): {cancellation}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY 环境变量！")
    dump_all_cancelled_postings()
