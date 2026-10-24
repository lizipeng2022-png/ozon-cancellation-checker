import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import datetime
import time
import sys

RAW_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
RAW_API_KEY = os.environ.get("OZON_API_KEY", "")
PUSHPLUS_TOKEN = (os.environ.get("PUSHPLUS_TOKEN") or "").strip()

CLIENT_ID = "".join([c for c in RAW_CLIENT_ID if ord(c) < 128]).strip()
API_KEY = "".join([c for c in RAW_API_KEY if ord(c) < 128]).strip()

BASE_URL = "https://api-seller.ozon.ru"

headers = {
    "Client-Id": CLIENT_ID,
    "Api-Key": API_KEY,
    "Content-Type": "application/json"
}

session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[500, 502, 503, 504],
    raise_on_status=False
)
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

def safe_post(url, json_data, max_attempts=3):
    """带网络超时重试的 POST 函数"""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = session.post(url, headers=headers, json=json_data, timeout=60)
            return resp
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            print(f"  [网络提示] 连接 Ozon 出现超时 ({e.__class__.__name__})，正在进行第 {attempt}/{max_attempts} 次自动重试...")
            time.sleep(3)
    return None

def is_client_or_seller(initiator_str):
    """
    判断取消过失方是否为买家或卖家
    """
    if not initiator_str:
        return False
    init = str(initiator_str).strip()
    if init in ["Клиент", "Продавец"]:
        return True
    return False

def parse_iso_datetime(dt_str):
    """解析 RFC3339 / ISO 格式时间戳"""
    if not dt_str:
        return None
    try:
        clean_str = dt_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(clean_str)
    except Exception:
        return None

def filter_claimable_orders():
    now = datetime.datetime.now(datetime.timezone.utc)
    TOTAL_DAYS = 150
    STEP_DAYS = 30  # 每 30 天一段回溯

    print("=" * 80)
    print(f"当前运行时间 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"【索赔目标窗口】取消满 60 天 且 未超过 90 天 (60 <= 取消天数 <= 90)")
    print("【过滤规则】1. 必须是真实取消订单 (status == 'cancelled')")
    print("            2. 排除买家('Клиент')与卖家('Продавец')")
    print("            3. 取消时间严格落在 60~90 天窗口内")
    print("=" * 80)

    matched_orders = {}
    total_cancelled_scanned = 0
    non_client_seller_count = 0

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
            if cursor:
                payload["cursor"] = cursor

            resp = safe_post(f"{BASE_URL}/v4/posting/fbs/list", payload)
            if resp is None or resp.status_code != 200:
                break

            data = resp.json()
            postings = data.get("postings") or data.get("result", {}).get("postings", [])
            if not postings:
                break

            for item in postings:
                # 规则 1: 必须是已取消包裹
                if item.get("status") != "cancelled":
                    continue

                total_cancelled_scanned += 1
                cancellation = item.get("cancellation", {})
                initiator = cancellation.get("cancellation_initiator")

                # 规则 2: 排除买家与卖家责任
                if is_client_or_seller(initiator):
                    continue

                non_client_seller_count += 1
                posting_num = item.get("posting_number")

                # 获取订单的取消时间
                cancel_time_raw = (
                    cancellation.get("cancellation_date") or 
                    item.get("delivering_date") or 
                    item.get("in_process_at")
                )
                cancel_dt = parse_iso_datetime(cancel_time_raw)
                
                days_since_cancel = (now - cancel_dt).days if cancel_dt else -1

                # 规则 3: 严格二次过滤，取消时间必须满 60 天且不超过 90 天
                if not (60 <= days_since_cancel <= 90):
                    continue

                if posting_num not in matched_orders:
                    matched_orders[posting_num] = {
                        "posting_number": posting_num,
                        "initiator": initiator if initiator else "未填写",
                        "reason": cancellation.get("cancel_reason"),
                        "reason_id": cancellation.get("cancel_reason_id"),
                        "cancel_time": cancel_time_raw,
                        "days_since_cancel": days_since_cancel,
                        "in_process_at": item.get("in_process_at"),
                        "tracking_number": item.get("tracking_number")
                    }

            has_next = data.get("has_next", False)
            next_cursor = data.get("cursor", "")
            if not has_next or not next_cursor or next_cursor == cursor:
                break

            cursor = next_cursor
            page += 1

    print("\n" + "=" * 80)
    print(f"【扫描汇总】总取消单: {total_cancelled_scanned} 笔 | 非买/卖家责任: {non_client_seller_count} 笔")
    print(f"【索赔窗口命中】刚好取消满 60~90 天的可直接索赔订单: {len(matched_orders)} 笔")
    print("=" * 80 + "\n")

    for idx, o in enumerate(matched_orders.values(), 1):
        print(f"[{idx}] 货件号: {o['posting_number']}")
        print(f"    - 取消过失方: 【{o['initiator']}】")
        print(f"    - 取消原因: 【{o['reason']}】 (ID: {o['reason_id']})")
        print(f"    - 取消时间: {o['cancel_time']} (已取消 {o['days_since_cancel']} 天，处于 60~90 天索赔期)")
        print(f"    - 运单号: {o['tracking_number']}\n")

    # 推送至微信
    if PUSHPLUS_TOKEN and matched_orders:
        push_lines = [
            f"### 【Ozon 60~90天索赔黄金期订单】共 {len(matched_orders)} 笔\n",
            "> 筛选条件：已取消满 60 天且在 90 天索赔有效期内 + 物流/官方责任\n"
        ]
        for o in list(matched_orders.values())[:30]:
            push_lines.append(
                f"- **货件号**: `{o['posting_number']}`\n"
                f"  - 过失方: `{o['initiator']}` | 已取消: `{o['days_since_cancel']}天`\n"
                f"  - 原因: {o['reason']}\n"
                f"  - 运单号: `{o['tracking_number']}`\n"
            )
        try:
            requests.post(
                "http://www.pushplus.plus/send",
                json={
                    "token": PUSHPLUS_TOKEN,
                    "title": f"【Ozon索赔】{len(matched_orders)} 笔订单已满60天待索赔",
                    "content": "\n".join(push_lines),
                    "template": "markdown"
                },
                timeout=10
            )
            print("✓ PushPlus 微信通知已成功推送！")
        except Exception as e:
            print(f"PushPlus 推送异常: {e}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    filter_claimable_orders()
