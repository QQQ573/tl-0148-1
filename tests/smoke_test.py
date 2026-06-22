"""
简单冒烟测试脚本（不依赖外部框架）

使用：
    docker-compose up -d
    # 等待服务就绪
    python tests/smoke_test.py
"""

import urllib.request
import urllib.parse
import json
import time
import sys

BASE = "http://localhost:8000"


def _req(method, path, data=None, token=None, form=False):
    headers = {}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")
    except Exception as e:
        return 0, {"error": str(e)}


def step(name, fn):
    print(f"\n▶ {name} ... ", end="")
    try:
        res = fn()
        print(f"✅ {res}")
        return res
    except AssertionError as e:
        print(f"❌ 断言失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 异常: {e}")
        sys.exit(1)


def main():
    print("=" * 60)
    print("  非遗泥塑工坊预约系统 · 冒烟测试")
    print("=" * 60)

    # 1. health
    def _h():
        code, d = _req("GET", "/health")
        assert code == 200, f"status={code}"
        assert d.get("database") is True, "DB 未就绪"
        return f"redis={d.get('redis')}"
    step("1. 健康检查 /health", _h)

    # 2. manager login
    manager_tok = None
    def _m():
        nonlocal manager_tok
        code, d = _req("POST", "/api/v1/auth/login", {"username": "manager", "password": "123456"}, form=True)
        assert code == 200 and d.get("data", {}).get("access_token"), f"登录失败: {d}"
        manager_tok = d["data"]["access_token"]
        return "OK"
    step("2. 坊管家登录", _m)

    # 3. list classes
    classes = []
    def _c():
        nonlocal classes
        code, d = _req("GET", "/api/v1/classes?page_size=10", token=manager_tok)
        assert code == 200, f"status={code}"
        classes = d.get("data", {}).get("items", [])
        return f"共 {len(classes)} 节课程"
    step("3. 拉取大师课列表", _c)

    if not classes:
        print("⚠ 暂无课程数据，跳过后续测试，请检查种子数据是否播种")
        return
    class_id = classes[0]["id"]
    class_title = classes[0]["title"]
    print(f"   选择课程: ID={class_id}  {class_title}")

    # 4. register student
    stu_tok = None
    def _s():
        nonlocal stu_tok
        ts = int(time.time())
        payload = {
            "username": f"smoke_{ts}",
            "email": f"smoke_{ts}@test.local",
            "password": "123456",
            "full_name": "冒烟测试学员",
            "role": "student",
        }
        code, d = _req("POST", "/api/v1/auth/register", payload)
        if code not in (200, 400):
            assert False, f"注册失败 {code}: {d}"
        code2, d2 = _req("POST", "/api/v1/auth/login", {"username": payload["username"], "password": "123456"}, form=True)
        assert code2 == 200, f"学员登录失败: {d2}"
        stu_tok = d2["data"]["access_token"]
        return f"stu={payload['username']}"
    step("4. 学员自助注册+登录", _s)

    # 5. 创建预约 (DRAFT)
    booking_id = None
    booking_no = None
    version = None
    def _b():
        nonlocal booking_id, booking_no, version
        payload = {
            "master_class_id": class_id,
            "gaobai_ni_kg": "1.0",
            "hongtao_kg": "0.5",
            "xianwei_ni_kg": "0.2",
            "student_remark": "冒烟测试",
        }
        code, d = _req("POST", "/api/v1/bookings", payload, token=stu_tok)
        assert code == 200 and d.get("data", {}).get("id"), f"创建失败: {d}"
        booking_id = d["data"]["id"]
        booking_no = d["data"]["booking_no"]
        version = d["data"]["version"]
        assert d["data"]["status"] == "draft"
        return f"booking={booking_no} v{version}"
    step("5. 学员创建预约单(DRAFT)", _b)

    # 6. 学员提交 -> PENDING_QUOTA
    def _sq():
        nonlocal version
        payload = {"version": version, "remark": "请审批"}
        code, d = _req("POST", f"/api/v1/bookings/{booking_id}/submit-quota", payload, token=stu_tok)
        assert code == 200, f"提交失败 {code}: {d}"
        assert d["data"]["status"] == "pending_quota"
        version = d["data"]["version"]
        return f"new_version={version}"
    step("6. 学员提交配额确认", _sq)

    # 7. 坊管家 配额审批 -> PENDING_SIGNATURE
    def _aq():
        nonlocal version
        payload = {"version": version, "remark": "配额充足"}
        code, d = _req("POST", f"/api/v1/bookings/{booking_id}/approve-quota", payload, token=manager_tok)
        assert code == 200, f"配额审批失败 {code}: {d}"
        assert d["data"]["status"] == "pending_signature", f"状态={d['data']['status']}"
        version = d["data"]["version"]
        return f"new_version={version}"
    step("7. 坊管家配额审批通过", _aq)

    # 8. 大师登录 & 签字 -> PENDING_PAYMENT
    master_tok = None
    def _ml():
        nonlocal master_tok
        code, d = _req("POST", "/api/v1/auth/login", {"username": "master1", "password": "123456"}, form=True)
        assert code == 200
        master_tok = d["data"]["access_token"]
        return "OK"
    step("8. 大师登录", _ml)

    def _sg():
        nonlocal version
        payload = {"version": version, "remark": "同意授课"}
        code, d = _req("POST", f"/api/v1/bookings/{booking_id}/sign", payload, token=master_tok)
        assert code == 200, f"签字失败 {code}: {d}"
        assert d["data"]["status"] == "pending_payment"
        version = d["data"]["version"]
        return f"new_version={version}"
    step("9. 大师签字确认", _sg)

    # 10. 财务 缴费确认 -> CONFIRMED
    finance_tok = None
    def _fl():
        nonlocal finance_tok
        code, d = _req("POST", "/api/v1/auth/login", {"username": "finance", "password": "123456"}, form=True)
        assert code == 200
        finance_tok = d["data"]["access_token"]
        return "OK"
    step("10. 财务登录", _fl)

    def _cp():
        nonlocal version
        payload = {"version": version, "paid_amount": "888.00", "remark": "已收到全款"}
        code, d = _req("POST", f"/api/v1/bookings/{booking_id}/confirm-payment", payload, token=finance_tok)
        assert code == 200, f"缴费失败 {code}: {d}"
        assert d["data"]["status"] == "confirmed"
        version = d["data"]["version"]
        return f"new_version={version}"
    step("11. 财务缴费确认 -> 已确认 ✅", _cp)

    # 12. 乐观锁测试（version 错误 -> 409）
    def _ol():
        payload = {"version": 1, "remark": "测试冲突"}
        code, d = _req("POST", f"/api/v1/bookings/{booking_id}/submit-quota", payload, token=stu_tok)
        assert code == 409 or code == 400, f"乐观锁未生效 code={code}"
        return f"code={code} 正常拦截"
    step("12. 乐观锁冲突验证", _ol)

    # 13. 同一学员同月去重
    def _dup():
        payload = {
            "master_class_id": class_id,
            "gaobai_ni_kg": "0.5",
            "hongtao_kg": "0.5",
            "xianwei_ni_kg": "0.5",
        }
        code, d = _req("POST", "/api/v1/bookings", payload, token=stu_tok)
        msg = str(d)
        assert code == 400 or ("重复" in msg) or ("进行中" in msg), f"去重未生效 code={code} {d}"
        return f"code={code} 去重生效"
    step("13. 同月重复预约去重验证", _dup)

    # 14. 状态流转日志
    def _lg():
        code, d = _req("GET", f"/api/v1/bookings/{booking_id}/logs", token=stu_tok)
        assert code == 200 and len(d.get("data", [])) >= 5, f"日志异常: {d}"
        return f"共 {len(d['data'])} 条状态日志"
    step("14. 状态流转日志完整", _lg)

    print("\n" + "=" * 60)
    print("🎉 冒烟测试全部通过！预约状态完整流转:")
    print("  DRAFT → PENDING_QUOTA → PENDING_SIGNATURE → PENDING_PAYMENT → CONFIRMED")
    print("=" * 60)


if __name__ == "__main__":
    main()
