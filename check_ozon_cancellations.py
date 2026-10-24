import os
import requests
import datetime
import json
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

def is_client_or_seller(initiator_str):
    """
    判断取消过失方是否为 买家 或 卖家（支持中英俄文判断）
    """
    if not initiator_str:
        return False
    init = str(initiator_str).lower().strip()
    # 买家特征
    if any(k in init for k in ["клиент", "покупатель", "client", "buyer", "买家"]):
        return True
    # 卖家特征
    if any(k in init for k in ["продавец", "seller", "卖家"]):
        return True
    return False

def run_checker():
    now = datetime.datetime.now(datetime.timezone.utc)
    TOTAL_DAYS = 150
    STEP_DAYS = 15  # 按 15 天为一个切片回溯过去 150 天

    print("=" * 70)
    print(f"当前运行时间 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"【开始扫描】动态回溯过去 {TOTAL_DAYS} 天已取消订单")
    print("【筛选标准】取消过失方 (cancellation_initiator) 非买家 且 非卖家")
    print("=" * 70)

    matched_orders = {}
    all_cancelled_count = 0
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
                "offset": offset,
                "with": {
                    "analytics_data": True,
                    "financial_data": True
                }
            }

            resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                print(f"区间 {since_str[:10]}~{to_str[:10]} 请求异常 ({resp.status_code}): {resp.text}")
                break

            data = resp.json()
            # 关键修复：v4 接口 postings 直接在顶层返回！
            postings = data.get("postings") or data.get("result", {}).get("postings", [])
            if not postings:
                break

            all_cancelled_count += len(postings)
            print(f"✓ 区间 {since_str[:10]} ~ {to_str[:10]} (offset={offset}) 成功读取 {len(postings)} 笔取消订单")

            for item in postings:
                cancellation = item.get("cancellation", {})
                initiator = cancellation.get("cancellation_initiator") or ""
                all_initiators.add(initiator)

                # 过滤掉买家与卖家责任
                if is_client_or_seller(initiator):
                    continue

                posting_num = item.get("posting_number")
                if posting_num not in matched_orders:
                    amount = sum(float(p.get("price", 0)) for p in item.get("products", []))
                    currency = item.get("products", [{}])[0].get("currency_code", "USD")
                    matched_orders[posting_num] = {
                        "posting_number": posting_num,
                        "initiator": initiator if initiator else "未标记(非买/卖家)",
                        "reason": cancellation.get("cancel_reason"),
                        "reason_id": cancellation.get("cancel_reason_id"),
                        "amount": f"{amount:.2f} {currency}",
                        "tracking_number": item.get("tracking_number"),
                        "in_process_at": item.get("in_process_at")
                    }

            has_next = data.get("has_next") if "has_next" in data else data.get("result", {}).get("has_next", False)
            if not has_next:
                break
            offset += limit

    print("\n" + "=" * 70)
    print(f"【全部出现过的过失方类型 (供核对拼写)】: {list(all_initiators)}")
    print(f"【扫描汇总】过去 {TOTAL_DAYS} 天共拉取到 {all_cancelled_count} 笔已取消订单")
    print(f"【索赔符合】其中非买/卖家责任（可索赔）共 {len(matched_orders)} 笔：")
    print("=" * 70 + "\n")

    for idx, o in enumerate(matched_orders.values(), 1):
        print(f"[{idx}] 货件号: {o['posting_number']}")
        print(f"    - 取消过失方: {o['initiator']}")
        print(f"    - 取消原因: {o['reason']} (ID: {o['reason_id']})")
        print(f"    - 订单金额: {o['amount']} | 运单号: {o['tracking_number']}")
        print(f"    - 下单时间: {o['in_process_at']}\n")

    # 微信 PushPlus 推送通知
    if PUSHPLUS_TOKEN and matched_orders:
        push_lines = [f"### 【Ozon 索赔提醒】发现 {len(matched_orders)} 笔非买/卖家责任订单\n"]
        for o in matched_orders.values():
            push_lines.append(
                f"- **货件号**: `{o['posting_number']}`\n"
                f"  - 过失方: `{o['initiator']}`\n"
                f"  - 原因: {o['reason']}\n"
                f"  - 金额: {o['amount']}\n"
                f"  - 运单号: `{o['tracking_number']}`\n"
            )
        try:
            requests.post(
                "http://www.pushplus.plus/send",
                json={
                    "token": PUSHPLUS_TOKEN,
                    "title": f"【Ozon索赔】{len(matched_orders)} 笔责任取消订单待处理",
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
    run_checker()import os
import requests
import datetime
import json
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

def is_client_or_seller(initiator_str):
    """
    判断取消过失方是否为 买家 或 卖家（支持中英俄文判断）
    """
    if not initiator_str:
        return False
    init = str(initiator_str).lower().strip()
    # 买家特征
    if any(k in init for k in ["клиент", "покупатель", "client", "buyer", "买家"]):
        return True
    # 卖家特征
    if any(k in init for k in ["продавец", "seller", "卖家"]):
        return True
    return False

def run_checker():
    now = datetime.datetime.now(datetime.timezone.utc)
    TOTAL_DAYS = 150
    STEP_DAYS = 15  # 按 15 天为一个切片回溯过去 150 天

    print("=" * 70)
    print(f"当前运行时间 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"【开始扫描】动态回溯过去 {TOTAL_DAYS} 天已取消订单")
    print("【筛选标准】取消过失方 (cancellation_initiator) 非买家 且 非卖家")
    print("=" * 70)

    matched_orders = {}
    all_cancelled_count = 0
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
                "offset": offset,
                "with": {
                    "analytics_data": True,
                    "financial_data": True
                }
            }

            resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                print(f"区间 {since_str[:10]}~{to_str[:10]} 请求异常 ({resp.status_code}): {resp.text}")
                break

            data = resp.json()
            # 关键修复：v4 接口 postings 直接在顶层返回！
            postings = data.get("postings") or data.get("result", {}).get("postings", [])
            if not postings:
                break

            all_cancelled_count += len(postings)
            print(f"✓ 区间 {since_str[:10]} ~ {to_str[:10]} (offset={offset}) 成功读取 {len(postings)} 笔取消订单")

            for item in postings:
                cancellation = item.get("cancellation", {})
                initiator = cancellation.get("cancellation_initiator") or ""
                all_initiators.add(initiator)

                # 过滤掉买家与卖家责任
                if is_client_or_seller(initiator):
                    continue

                posting_num = item.get("posting_number")
                if posting_num not in matched_orders:
                    amount = sum(float(p.get("price", 0)) for p in item.get("products", []))
                    currency = item.get("products", [{}])[0].get("currency_code", "USD")
                    matched_orders[posting_num] = {
                        "posting_number": posting_num,
                        "initiator": initiator if initiator else "未标记(非买/卖家)",
                        "reason": cancellation.get("cancel_reason"),
                        "reason_id": cancellation.get("cancel_reason_id"),
                        "amount": f"{amount:.2f} {currency}",
                        "tracking_number": item.get("tracking_number"),
                        "in_process_at": item.get("in_process_at")
                    }

            has_next = data.get("has_next") if "has_next" in data else data.get("result", {}).get("has_next", False)
            if not has_next:
                break
            offset += limit

    print("\n" + "=" * 70)
    print(f"【全部出现过的过失方类型 (供核对拼写)】: {list(all_initiators)}")
    print(f"【扫描汇总】过去 {TOTAL_DAYS} 天共拉取到 {all_cancelled_count} 笔已取消订单")
    print(f"【索赔符合】其中非买/卖家责任（可索赔）共 {len(matched_orders)} 笔：")
    print("=" * 70 + "\n")

    for idx, o in enumerate(matched_orders.values(), 1):
        print(f"[{idx}] 货件号: {o['posting_number']}")
        print(f"    - 取消过失方: {o['initiator']}")
        print(f"    - 取消原因: {o['reason']} (ID: {o['reason_id']})")
        print(f"    - 订单金额: {o['amount']} | 运单号: {o['tracking_number']}")
        print(f"    - 下单时间: {o['in_process_at']}\n")

    # 微信 PushPlus 推送通知
    if PUSHPLUS_TOKEN and matched_orders:
        push_lines = [f"### 【Ozon 索赔提醒】发现 {len(matched_orders)} 笔非买/卖家责任订单\n"]
        for o in matched_orders.values():
            push_lines.append(
                f"- **货件号**: `{o['posting_number']}`\n"
                f"  - 过失方: `{o['initiator']}`\n"
                f"  - 原因: {o['reason']}\n"
                f"  - 金额: {o['amount']}\n"
                f"  - 运单号: `{o['tracking_number']}`\n"
            )
        try:
            requests.post(
                "http://www.pushplus.plus/send",
                json={
                    "token": PUSHPLUS_TOKEN,
                    "title": f"【Ozon索赔】{len(matched_orders)} 笔责任取消订单待处理",
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
    run_checker()
