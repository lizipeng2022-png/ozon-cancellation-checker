import os
import requests
import datetime
import json
import sys

RAW_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
RAW_API_KEY = os.environ.get("OZON_API_KEY", "")
PUSHPLUS_TOKEN = (os.environ.get("PUSHPLUS_TOKEN") or "").strip()

# 允许在 Actions 手动触发时输入进单起止时间，若未传则默认查过去 150 天
INPUT_SINCE = os.environ.get("START_DATE")
INPUT_TO = os.environ.get("END_DATE")

CLIENT_ID = "".join([c for c in RAW_CLIENT_ID if ord(c) < 128]).strip()
API_KEY = "".join([c for c in RAW_API_KEY if ord(c) < 128]).strip()

BASE_URL = "https://api-seller.ozon.ru"

headers = {
    "Client-Id": CLIENT_ID,
    "Api-Key": API_KEY,
    "Content-Type": "application/json"
}

def format_rfc3339(date_str, is_end=False):
    if not date_str:
        return None
    time_suffix = "23:59:59Z" if is_end else "00:00:00Z"
    return f"{date_str.strip()}T{time_suffix}"

def is_client_or_seller(initiator_str):
    """
    判断取消过失方是否为 买家 或 卖家（同时支持中英俄文判断）
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

def get_claimable_orders():
    now = datetime.datetime.now(datetime.timezone.utc)
    default_since = (now - datetime.timedelta(days=150)).strftime("%Y-%m-%dT00:00:00Z")
    default_to = now.strftime("%Y-%m-%dT23:59:59Z")

    since = format_rfc3339(INPUT_SINCE, False) or default_since
    to = format_rfc3339(INPUT_TO, True) or default_to

    print("=" * 60)
    print(f"【开始筛查可索赔取消订单】进单区间: {since[:10]} 至 {to[:10]}")
    print("【筛选规则】取消过失方 (cancellation_initiator) != 买家 且 != 卖家")
    print("=" * 60)

    offset = 0
    limit = 100
    matched_orders = []

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

        resp = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"Ozon API 请求失败: {resp.status_code}, {resp.text}")
            sys.exit(1)

        data = resp.json()
        postings = data.get("result", {}).get("postings", [])
        if not postings:
            break

        for item in postings:
            cancellation = item.get("cancellation", {})
            initiator = cancellation.get("cancellation_initiator") or ""
            reason = cancellation.get("cancel_reason") or ""
            
            # 核心规则：过滤掉买家与卖家，只保留第三方配送、Ozon官方等其他过失方
            if is_client_or_seller(initiator):
                continue

            # 计算订单金额
            amount = sum(float(p.get("price", 0)) for p in item.get("products", []))
            currency = item.get("products", [{}])[0].get("currency_code", "USD")

            matched_orders.append({
                "posting_number": item.get("posting_number"),
                "initiator": initiator if initiator else "未标注(非买家/卖家)",
                "reason": reason,
                "cancel_reason_id": cancellation.get("cancel_reason_id"),
                "tracking_number": item.get("tracking_number"),
                "in_process_at": item.get("in_process_at"),
                "amount": f"{amount:.2f} {currency}"
            })

        if not data.get("result", {}).get("has_next", False):
            break
        offset += limit

    # 打印排查结果
    print(f"\n【筛查结果】共发现 {len(matched_orders)} 笔非买家/卖家责任的取消订单（可索赔）：\n")
    for idx, o in enumerate(matched_orders, 1):
        print(f"[{idx}] 货件号: {o['posting_number']}")
        print(f"    - 取消过失方: {o['initiator']}")
        print(f"    - 取消原因: {o['reason']} (ID: {o['cancel_reason_id']})")
        print(f"    - 货件金额: {o['amount']}")
        print(f"    - 运单号: {o['tracking_number']}")
        print(f"    - 下单时间: {o['in_process_at']}\n")

    # 推送微信通知（若配置了 PushPlus）
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
            print("PushPlus 微信通知已成功送达！")
        except Exception as e:
            print(f"PushPlus 推送异常: {e}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    get_claimable_orders()
