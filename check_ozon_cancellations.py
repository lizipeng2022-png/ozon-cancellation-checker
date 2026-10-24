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

# 带有自动重试机制的 Session
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
    若未填写过失方（None 或空字符串），返回 False（保留输出给人工甄别）
    """
    if not initiator_str:
        return False
    init = str(initiator_str).strip()
    if init in ["Клиент", "Продавец"]:
        return True
    return False

def filter_claimable_orders():
    now = datetime.datetime.now(datetime.timezone.utc)
    TOTAL_DAYS = 150
    STEP_DAYS = 30  # 每 30 天一段，分 5 段拉取过去 150 天

    print("=" * 80)
    print(f"当前运行时间 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"【索赔/待甄别订单筛查】正在扫描过去 {TOTAL_DAYS} 天内所有已取消订单")
    print("【过滤规则】排除 'Клиент'(买家) 与 'Продавец'(卖家)；保留物流/官方/未填写的订单")
    print("=" * 80)

    matched_orders = {}
    total_cancelled_scanned = 0

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
                status_info = resp.status_code if resp else "超时无响应"
                text_info = resp.text if resp else ""
                print(f"区间 {since_str[:10]}~{to_str[:10]} 请求异常 ({status_info}): {text_info}")
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

                total_cancelled_scanned += 1

                # 排除买家与卖家责任
                if is_client_or_seller(initiator):
                    continue

                if posting_num not in matched_orders:
                    new_count += 1
                    matched_orders[posting_num] = {
                        "posting_number": posting_num,
                        "status": item.get("status"),
                        "initiator": initiator if initiator else "未填写(需人工甄别)",
                        "reason": reason if reason else "未填写",
                        "reason_id": reason_id,
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
    print(f"【扫描汇总】共扫描已取消订单 {total_cancelled_scanned} 笔")
    print(f"【筛选结果】排除买家/卖家后，共提取出 {len(matched_orders)} 笔待处理/可索赔订单：")
    print("=" * 80 + "\n")

    for idx, o in enumerate(matched_orders.values(), 1):
        print(f"[{idx}] 货件号: {o['posting_number']}")
        print(f"    - 取消过失方: 【{o['initiator']}】")
        print(f"    - 取消原因: 【{o['reason']}】 (ID: {o['reason_id']})")
        print(f"    - 运单号: {o['tracking_number']} | 进单时间: {o['in_process_at']}\n")

    # 微信 PushPlus 通知推送
    if PUSHPLUS_TOKEN and matched_orders:
        push_lines = [
            f"### 【Ozon 索赔/待甄别清单】共 {len(matched_orders)} 笔订单\n",
            "> 筛选规则：排除买家与卖家责任，保留物流/平台及未填写过失方的订单\n"
        ]
        # 控制推送单量避免微信消息过长截断（前 30 笔详细输出，超出部分提示查看日志）
        for o in list(matched_orders.values())[:30]:
            push_lines.append(
                f"- **货件号**: `{o['posting_number']}`\n"
                f"  - 过失方: `{o['initiator']}`\n"
                f"  - 原因: {o['reason']}\n"
                f"  - 运单号: `{o['tracking_number']}`\n"
            )
        if len(matched_orders) > 30:
            push_lines.append(f"\n*注：订单较多，更多明细请在 GitHub Actions 运行日志中查看。*")

        try:
            requests.post(
                "http://www.pushplus.plus/send",
                json={
                    "token": PUSHPLUS_TOKEN,
                    "title": f"【Ozon索赔提醒】发现 {len(matched_orders)} 笔非买/卖家责任订单",
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
    filter_claimable_orders()import os
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

# 带有自动重试机制的 Session
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
    若未填写过失方（None 或空字符串），返回 False（保留输出给人工甄别）
    """
    if not initiator_str:
        return False
    init = str(initiator_str).strip()
    if init in ["Клиент", "Продавец"]:
        return True
    return False

def filter_claimable_orders():
    now = datetime.datetime.now(datetime.timezone.utc)
    TOTAL_DAYS = 150
    STEP_DAYS = 30  # 每 30 天一段，分 5 段拉取过去 150 天

    print("=" * 80)
    print(f"当前运行时间 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"【索赔/待甄别订单筛查】正在扫描过去 {TOTAL_DAYS} 天内所有已取消订单")
    print("【过滤规则】排除 'Клиент'(买家) 与 'Продавец'(卖家)；保留物流/官方/未填写的订单")
    print("=" * 80)

    matched_orders = {}
    total_cancelled_scanned = 0

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
                status_info = resp.status_code if resp else "超时无响应"
                text_info = resp.text if resp else ""
                print(f"区间 {since_str[:10]}~{to_str[:10]} 请求异常 ({status_info}): {text_info}")
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

                total_cancelled_scanned += 1

                # 排除买家与卖家责任
                if is_client_or_seller(initiator):
                    continue

                if posting_num not in matched_orders:
                    new_count += 1
                    matched_orders[posting_num] = {
                        "posting_number": posting_num,
                        "status": item.get("status"),
                        "initiator": initiator if initiator else "未填写(需人工甄别)",
                        "reason": reason if reason else "未填写",
                        "reason_id": reason_id,
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
    print(f"【扫描汇总】共扫描已取消订单 {total_cancelled_scanned} 笔")
    print(f"【筛选结果】排除买家/卖家后，共提取出 {len(matched_orders)} 笔待处理/可索赔订单：")
    print("=" * 80 + "\n")

    for idx, o in enumerate(matched_orders.values(), 1):
        print(f"[{idx}] 货件号: {o['posting_number']}")
        print(f"    - 取消过失方: 【{o['initiator']}】")
        print(f"    - 取消原因: 【{o['reason']}】 (ID: {o['reason_id']})")
        print(f"    - 运单号: {o['tracking_number']} | 进单时间: {o['in_process_at']}\n")

    # 微信 PushPlus 通知推送
    if PUSHPLUS_TOKEN and matched_orders:
        push_lines = [
            f"### 【Ozon 索赔/待甄别清单】共 {len(matched_orders)} 笔订单\n",
            "> 筛选规则：排除买家与卖家责任，保留物流/平台及未填写过失方的订单\n"
        ]
        # 控制推送单量避免微信消息过长截断（前 30 笔详细输出，超出部分提示查看日志）
        for o in list(matched_orders.values())[:30]:
            push_lines.append(
                f"- **货件号**: `{o['posting_number']}`\n"
                f"  - 过失方: `{o['initiator']}`\n"
                f"  - 原因: {o['reason']}\n"
                f"  - 运单号: `{o['tracking_number']}`\n"
            )
        if len(matched_orders) > 30:
            push_lines.append(f"\n*注：订单较多，更多明细请在 GitHub Actions 运行日志中查看。*")

        try:
            requests.post(
                "http://www.pushplus.plus/send",
                json={
                    "token": PUSHPLUS_TOKEN,
                    "title": f"【Ozon索赔提醒】发现 {len(matched_orders)} 笔非买/卖家责任订单",
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
