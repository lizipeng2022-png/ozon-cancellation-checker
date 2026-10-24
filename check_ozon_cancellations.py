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
    if not initiator_str:
        return False
    init = str(initiator_str).lower().strip()
    if any(k in init for k in ["клиент", "покупатель", "client", "buyer", "买家"]):
        return True
    if any(k in init for k in ["продавец", "seller", "卖家"]):
        return True
    return False

def scan_claimable_cancellations():
    now = datetime.datetime.now(datetime.timezone.utc)
    TOTAL_DAYS = 120
    STEP_DAYS = 14  # 按14天切片，避免触发 Ozon 跨度限制

    print("=" * 70)
    print(f"【开始分段扫描】回溯 {TOTAL_DAYS} 天，步长 {STEP_DAYS} 天")
    print("【筛选规则】状态为取消，且取消过失方非买家、非卖家")
    print("=" * 70)

    matched_orders = {}

    for day_start in range(0, TOTAL_DAYS, STEP_DAYS):
        t_to = now - datetime.timedelta(days=day_start)
        t_since = now - datetime.timedelta(days=min(day_start + STEP_DAYS, TOTAL_DAYS))

        since_str = t_since.strftime("%Y-%m-%dT00:00:00Z")
        to_str = t_to.strftime("%Y-%m-%dT23:59:59Z")

        print(f"▶ 正在扫描区间: {since_str[:10]} 至 {to_str[:10]} ...")

        offset = 0
        limit = 100

        while True:
            # 不在 API 请求中强锁 status，拉取该区间全量订单在内存中筛查
            payload = {
                "dir": "DESC",
                "filter": {
                    "since": since_str,
                    "to": to_str
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
                print(f"  └ API 响应失败 ({resp.status_code}): {resp.text}")
                break

            data = resp.json()
            postings = data.get("result", {}).get("postings", [])
            if not postings:
                break

            for item in postings:
                cancellation = item.get("cancellation", {})
                status = item.get("status")
                
                # 仅保留已取消或包含有效取消节点的包裹
                if status != "cancelled" and not cancellation:
                    continue

                initiator = cancellation.get("cancellation_initiator") or ""
                
                # 排除买家与卖家责任
                if is_client_or_seller(initiator):
                    continue

                posting_num = item.get("posting_number")
                if posting_num not in matched_orders:
                    amount = sum(float(p.get("price", 0)) for p in item.get("products", []))
                    currency = item.get("products", [{}])[0].get("currency_code", "USD")
                    matched_orders[posting_num] = {
                        "posting_number": posting_num,
                        "initiator": initiator if initiator else "未标记责任方",
                        "reason": cancellation.get("cancel_reason"),
                        "reason_id": cancellation.get("cancel_reason_id"),
                        "amount": f"{amount:.2f} {currency}",
                        "tracking_number": item.get("tracking_number"),
                        "in_process_at": item.get("in_process_at")
                    }

            if not data.get("result", {}).get("has_next", False):
                break
            offset += limit

    print("\n" + "=" * 70)
    print(f"【筛查完成】共获取到 {len(matched_orders)} 笔非买/卖家责任的取消订单：")
    print("=" * 70)

    for idx, o in enumerate(matched_orders.values(), 1):
        print(f"[{idx}] 货件号: {o['posting_number']}")
        print(f"    - 取消过失方: {o['initiator']}")
        print(f"    - 取消原因: {o['reason']} (ID: {o['reason_id']})")
        print(f"    - 金额: {o['amount']} | 运单号: {o['tracking_number']}")
        print(f"    - 进单时间: {o['in_process_at']}\n")

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
            print("PushPlus 通知发送成功！")
        except Exception as e:
            print(f"PushPlus 推送异常: {e}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    scan_claimable_cancellations()
