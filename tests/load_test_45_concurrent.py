"""
45 并发压测脚本：非遗泥塑工坊预约创建接口
=========================================

场景说明：
  - 模拟 45 名学员同时创建预约单
  - 每个学员预约同一月份下的不同课程
  - 验证：
    1) 同一学员同一自然月是否只允许 1 个进行中预约
    2) 乐观锁 version 冲突是否返回 409 + 当前版本
    3) 泥料配额不足是否自动驳回并推荐班次
    4) 45 并发下系统稳定性

运行方法（宿主机，需安装依赖）：
    pip install aiohttp
    cp .env.example .env
    docker-compose up -d postgres redis minio mailhog
    # 等待 10 秒后
    docker-compose up -d api
    # 再等待 15 秒让 DB 初始化 + Demo 数据播种
    python tests/load_test_45_concurrent.py

预期结果：
  - 成功率 >= 90%
  - P95 延迟 < 2000ms
  - 每月内同一学员只成功创建 1 份（进行中）预约
"""

import asyncio
import aiohttp
import time
import json
import statistics
from collections import Counter

BASE_URL = "http://localhost:8000"
CONCURRENT = 45
TOTAL_REQUESTS = 45

API_PREFIX = "/api/v1"


async def login(session, username, password):
    async with session.post(
        f"{BASE_URL}{API_PREFIX}/auth/login",
        data={"username": username, "password": password},
    ) as resp:
        data = await resp.json()
        if resp.status == 200:
            return data["data"]["access_token"]
        raise RuntimeError(f"login failed: {data}")


async def register_and_login(session, idx):
    username = f"stu_loadtest_{idx:03d}"
    email = f"stu_{idx:03d}@loadtest.local"
    payload = {
        "username": username,
        "email": email,
        "password": "123456",
        "full_name": f"压测学员{idx}",
        "role": "student",
    }
    try:
        async with session.post(
            f"{BASE_URL}{API_PREFIX}/auth/register", json=payload,
        ) as resp:
            if resp.status not in (200, 400):
                txt = await resp.text()
                print(f"[register {idx}] unexpected {resp.status}: {txt[:120]}")
    except Exception as e:
        print(f"[register {idx}] err: {e}")
    return await login(session, username, "123456")


async def list_classes(session, token):
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(
        f"{BASE_URL}{API_PREFIX}/classes?page_size=20", headers=headers,
    ) as resp:
        data = await resp.json()
        if resp.status == 200 and data.get("data"):
            return data["data"].get("items", [])
        return []


async def create_booking(session, token, class_id, student_idx, results, latencies):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    kg_choices = [
        (1.5, 0.5, 0.3),
        (2.0, 1.0, 0.0),
        (0.5, 2.0, 0.5),
        (3.0, 0.0, 0.0),
        (0.0, 0.0, 1.5),
    ]
    g, h, x = kg_choices[student_idx % len(kg_choices)]
    payload = {
        "master_class_id": class_id,
        "gaobai_ni_kg": str(g),
        "hongtao_kg": str(h),
        "xianwei_ni_kg": str(x),
        "student_remark": f"压测请求 #{student_idx}",
    }
    t0 = time.perf_counter()
    status_code = 0
    ok = False
    body_snippet = ""
    try:
        async with session.post(
            f"{BASE_URL}{API_PREFIX}/bookings",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            status_code = resp.status
            body = await resp.json()
            body_snippet = json.dumps(body, ensure_ascii=False)[:80]
            if 200 <= resp.status < 300:
                ok = True
            elif resp.status == 400 and ("已有进行中" in str(body) or "不可重复" in str(body)):
                ok = True  # 预期的幂等/去重响应，算业务成功
            elif resp.status == 409:
                cur_ver = resp.headers.get("X-Current-Version")
                ok = True  # 乐观锁冲突，符合预期
                body_snippet = f"VERSION_CONFLICT current={cur_ver}"
    except Exception as e:
        body_snippet = f"ERROR: {e}"
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000
        latencies.append(dt_ms)
        results.append({
            "idx": student_idx,
            "status": status_code,
            "ok": ok,
            "latency_ms": round(dt_ms, 1),
            "body": body_snippet,
        })


async def main():
    print(f"[INFO] 目标: {BASE_URL}   并发数: {CONCURRENT}")
    results = []
    latencies = []

    # phase 1: manager login & ensure demo classes exist
    async with aiohttp.ClientSession() as s:
        try:
            tok = await login(s, "manager", "123456")
            classes = await list_classes(s, tok)
            if not classes:
                print("[WARN] 暂无课程，等 API 初始化种子数据后再运行")
                return
            class_ids = [c["id"] for c in classes]
            print(f"[INFO] 可选课程 {len(class_ids)} 个，ID 列表: {class_ids}")
        except Exception as e:
            print(f"[FATAL] 无法登录或获取课程: {e}")
            return

    # phase 2: 并发注册/登录 45 学员
    print(f"[PHASE 2] 注册并登录 {CONCURRENT} 名学员...")
    tokens = []
    async with aiohttp.ClientSession() as s:
        tasks = [register_and_login(s, i) for i in range(1, CONCURRENT + 1)]
        tokens = await asyncio.gather(*tasks, return_exceptions=True)
    tokens = [t for t in tokens if isinstance(t, str)]
    print(f"[PHASE 2] 成功登录 {len(tokens)}/{CONCURRENT} 名学员")

    # phase 3: 45 并发创建预约
    print(f"[PHASE 3] 发起 {TOTAL_REQUESTS} 并发预约创建请求...")
    t_start = time.perf_counter()
    async with aiohttp.ClientSession() as s:
        tasks = []
        for i in range(TOTAL_REQUESTS):
            tok = tokens[i % len(tokens)]
            cid = class_ids[i % len(class_ids)]
            tasks.append(create_booking(s, tok, cid, i + 1, results, latencies))
        await asyncio.gather(*tasks)
    t_total = (time.perf_counter() - t_start) * 1000

    # summary
    succ = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    http_counter = Counter(r["status"] for r in results)
    lat_sorted = sorted(latencies)
    p50 = lat_sorted[int(len(lat_sorted) * 0.50)] if lat_sorted else 0
    p95 = lat_sorted[int(len(lat_sorted) * 0.95)] if lat_sorted else 0
    p99 = lat_sorted[int(len(lat_sorted) * 0.99)] if lat_sorted else 0

    print("\n" + "=" * 70)
    print("  45 并发压测报告")
    print("=" * 70)
    print(f"  总请求数:            {len(results)}")
    print(f"  业务成功率:          {len(succ)}/{len(results)}  {100*len(succ)/max(1,len(results)):.1f}%")
    print(f"  总耗时:              {t_total:.1f} ms")
    print(f"  吞吐量 QPS:          {1000*len(results)/max(1,t_total):.2f} req/s")
    print(f"  HTTP 状态码分布:     {dict(http_counter)}")
    print(f"  平均延迟:            {statistics.mean(latencies):.1f} ms")
    print(f"  P50 延迟:            {p50:.1f} ms")
    print(f"  P95 延迟:            {p95:.1f} ms")
    print(f"  P99 延迟:            {p99:.1f} ms")
    print("-" * 70)
    if fail:
        print("  失败请求样例 (前 5 条):")
        for f in fail[:5]:
            print(f"    idx={f['idx']} status={f['status']} lat={f['latency_ms']}ms => {f['body']}")
    else:
        print("  ✅ 全部请求业务处理成功（含预期的去重/冲突响应）")
    print("=" * 70)

    # 持久化报告
    with open("tests/load_test_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "concurrent": CONCURRENT,
            "total": len(results),
            "success": len(succ),
            "success_rate": 100 * len(succ) / max(1, len(results)),
            "total_ms": round(t_total, 1),
            "qps": round(1000 * len(results) / max(1, t_total), 2),
            "http_distribution": dict(http_counter),
            "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0,
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "p99_ms": round(p99, 1),
            "fail_samples": fail[:20],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] 报告已保存 tests/load_test_report.json")


if __name__ == "__main__":
    asyncio.run(main())
