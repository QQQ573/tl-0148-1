from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio

from app.core.config import settings

celery_app = Celery(
    "clay_workshop_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "check-stale-bookings-every-hour": {
            "task": "app.tasks.email_tasks.check_stale_bookings",
            "schedule": 3600.0,
        },
    },
)


def _get_sync_session():
    engine = create_engine(settings.sync_db_url, pool_pre_ping=True)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _send_email(to_addr: str, subject: str, body_html: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM_EMAIL
        msg["To"] = to_addr
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] send to {to_addr} failed: {e}")
        return False


@celery_app.task(name="app.tasks.email_tasks.send_status_email")
def send_status_email(to_email: str, booking_no: str, status_name: str, extra: str = "") -> str:
    subject = f"【泥塑工坊】预约单 {booking_no} 状态更新 - {status_name}"
    body = f"""
    <div style="font-family: sans-serif; padding: 20px; max-width: 600px;">
        <h2 style="color: #8B4513;">非遗泥塑工坊</h2>
        <p>您好，</p>
        <p>您的预约单 <strong>{booking_no}</strong> 状态已更新为 <strong style="color: #D2691E;">{status_name}</strong>。</p>
        {f'<p>备注信息：{extra}</p>' if extra else ''}
        <p>请及时登录系统查看详情。</p>
        <hr style="border: none; border-top: 1px solid #eee;">
        <p style="color: #999; font-size: 12px;">此邮件由系统自动发送，请勿直接回复。</p>
    </div>
    """
    ok = _send_email(to_email, subject, body)
    return f"sent={ok} to={to_email}"


@celery_app.task(name="app.tasks.email_tasks.check_stale_bookings")
def check_stale_bookings() -> str:
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import and_, or_
    from app.models.user import Booking, BookingStatus, User

    SessionLocal = _get_sync_session()
    db = SessionLocal()
    try:
        hours = settings.QUOTA_ALERT_HOURS
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        active_statuses = [
            BookingStatus.DRAFT,
            BookingStatus.PENDING_QUOTA,
            BookingStatus.PENDING_SIGNATURE,
            BookingStatus.PENDING_PAYMENT,
        ]

        stale = db.query(Booking).filter(
            and_(
                Booking.status.in_(active_statuses),
                Booking.last_updated_at < threshold,
                or_(Booking.last_alerted_at.is_(None), Booking.last_alerted_at < threshold),
            )
        ).all()

        alerted_ids = []
        status_names_cn = {
            "draft": "草稿",
            "pending_quota": "待配额确认",
            "pending_signature": "待大师签字",
            "pending_payment": "待缴费",
        }

        for bk in stale:
            student = db.query(User).filter(User.id == bk.student_id).first()
            if not student:
                continue
            status_cn = status_names_cn.get(bk.status.value, bk.status.value)
            subject = f"【告警】预约单 {bk.booking_no} 已超过{hours}小时未更新"
            body = f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 600px;">
                <h2 style="color: #DC143C;">⚠ 流程停滞告警</h2>
                <p>预约单号：<strong>{bk.booking_no}</strong></p>
                <p>当前状态：<strong style="color: #D2691E;">{status_cn}</strong></p>
                <p>最后更新时间：{bk.last_updated_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p>该预约单已超过 <strong>{hours}小时</strong> 未推进，请相关人员及时处理！</p>
                <hr>
                <p style="color: #999; font-size: 12px;">系统自动告警邮件。</p>
            </div>
            """
            _send_email(student.email, subject, body)
            alerted_ids.append(bk.id)

        if alerted_ids:
            now = datetime.now(timezone.utc)
            db.query(Booking).filter(Booking.id.in_(alerted_ids)).update(
                {Booking.last_alerted_at: now}, synchronize_session=False
            )
            db.commit()

        return f"stale={len(stale)} alerted={len(alerted_ids)} ids={alerted_ids}"
    finally:
        db.close()


@celery_app.task(name="app.tasks.email_tasks.send_quota_reject_email")
def send_quota_reject_email(to_email: str, booking_no: str, reject_reason: str, recommendations: str = "") -> str:
    subject = f"【泥塑工坊】预约单 {booking_no} 泥料配额不足 - 自动驳回"
    body = f"""
    <div style="font-family: sans-serif; padding: 20px; max-width: 600px;">
        <h2 style="color: #DC143C;">预约单被驳回</h2>
        <p>您好，</p>
        <p>您的预约单 <strong>{booking_no}</strong> 因<strong>泥料配额不足</strong>被系统自动驳回。</p>
        <p><strong>原因：</strong>{reject_reason}</p>
        {f'<p><strong>推荐班次：</strong>{recommendations}</p>' if recommendations else ''}
        <p>请调整泥料需求或选择其他班次后重新提交。</p>
        <hr>
        <p style="color: #999; font-size: 12px;">系统自动发送。</p>
    </div>
    """
    ok = _send_email(to_email, subject, body)
    return f"reject_sent={ok}"
