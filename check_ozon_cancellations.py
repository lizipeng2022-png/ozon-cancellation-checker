import os
import requests
import datetime
import json
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

def check_orders():
    # 按照后台看到的 7月26日 ~ 8月25日 进单区间
    since = "2026-07-26T00:00:00Z"
    to = "2026-08-26T00:00:00Z"

    print("=" * 60)
    print(f"正在诊断查询 Ozon 订单 (进单周期: {since} 至 {to})")
    print("=" * 60)

    # 1. 尝试直接查询后台看到的具体取消单号，确认 API Key 权限和该单号的真实接口归属
    test_posting = "62662023-0335-1"
    print(f"\n[测试 1] 正在通过单号直接反查: {test_posting} ...")
    resp_single = requests.post(
        f"{BASE_URL}/v3/posting/fbs/get",
        headers=headers,
        json={"posting_number": test_posting, "with": {"analytics_data": True, "financial_data": True}},
        timeout=30
    )
    print(f"单号查询响应码: {resp_single.status_code}")
    if resp_single.status_code == 200:
        print("【成功找到该订单！】其完整结构如下：")
        print(json.dumps(resp_single.json(), indent=2, ensure_ascii=False))
        return
    else:
        print(f"单号直接查询返回: {resp_single.text}")

    # 2. 如果单号接口返回成功，测试常规列表接口
    print("\n[测试 2] 尝试不带 status 过滤拉取列表（排除状态枚举值不匹配问题）...")
    payload = {
        "dir": "DESC",
        "filter": {
            "since": since,
            "to": to
        },
        "limit": 50,
        "offset": 0
    }
    resp_list = requests.post(f"{BASE_URL}/v4/posting/fbs/list", headers=headers, json=payload, timeout=30)
    print(f"列表响应码: {resp_list.status_code}")
    data = resp_list.json()
    postings = data.get("result", {}).get("postings", [])
    print(f"不带状态过滤获取到订单数: {len(postings)}")
    if postings:
        statuses = set(p.get("status") for p in postings)
        print(f"返回订单中包含的所有状态值枚举: {statuses}")

if __name__ == "__main__":
    if not CLIENT_ID or not API_KEY:
        raise ValueError("请检查 OZON_CLIENT_ID 和 OZON_API_KEY！")
    check_orders()
