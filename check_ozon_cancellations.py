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

def scan_all_cancellations():
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # 覆盖从 8 月 1 日至今的所有数据（覆盖订单进单和 10 月实际取消的全周期）
    since_str = "2026-08-01T00:00:00Z"
    to_str = now.strftime("%Y-%m-%dT23:59:59Z")

    print("=" * 70)
    print(f"【开始筛查】时间跨度: {since_str[:10]} 至 {to_str[:10]}")
    print("【责任规则】取消过失方 (cancellation_initiator) 非买家 且 非卖家")
    print("=" * 70)

    offset = 0
    limit = 50
    matched_orders = []
    total_scanned = 0

    while True:
        payload = {
            "dir": "DESC",
            "filter": {
                "since": since_str,
                "to": to_str
            },
            "limit": limit,
            "offset": offset,
            "with": {
                "financial_data": True
            }
        }

        resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"API 请求失败: {resp.status_code}, {resp.text}")
            break

        data = resp.json()
        postings = data.get("result", {}).get("postings", [])
        if not postings:
            break

        total_scanned += len(postings)

        for item in postings:
            status = item.get("status")
            cancellation = item.get("cancellation", {})

            # 只要是已取消订单
            if status == "cancelled" or cancellation:
                initiator = cancellation.get("cancellation_initiator") or ""
                
                # 排除买家和卖家责任
                if is_client_or_seller(initiator):
                    continue

                amount = sum(float(p.get("price", 0)) for p in item.get("products", []))
                currency = item.get("products", [{}])[0].get("currency_code", "USD")

                matched_orders.append({
                    "posting_number": item.get("posting_number"),
                    "initiator": initiator if initiator else "未标记责任方",
                    "reason": cancellation.get("cancel_reason"),
                    "reason_id": cancellation.get("cancel_reason_id"),
                    "amount": f"{amount:.2f} {currency}",
                    "tracking_number": item.get("tracking_number"),
                    "in_process_at": item.get("in_process_at")
                })

        if not data.get("result", {}).get("has_next", False):
            break
        offset += limit

    print(f"\n【扫描统计】共扫描 {total_scanned} 笔订单，发现 {len(matched_orders)} 笔非买/卖家责任的取消订单：\n")
    for idx, o in enumerate(matched_orders, 1):
        print(f"[{idx}] 货件号: {o['posting_number']}")
        print(f"    - 取消过失方: {o['initiator']}")
        print(f"    - 取消原因: {o['reason']} (ID: {o['reason_id']})")
        print(f"    - 订单金额: {o['amount']} | 运单号: {o['tracking_number']}")
        print(f"    - 下单时间: {o['in_process_at']}\n")

    if PUSHPLUS_TOKEN and matched_orders:
        push_lines = [f"### 【Ozon 索赔提醒】发现 {len(matched_orders)} 笔非买/卖家责任订单\n"]
        for o in matched_orders:
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
            print("PushPlus 微信通知已发送！")
        except Exception as e:
            print(f"PushPlus 推送异常: {e}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    scan_all_cancellations()
