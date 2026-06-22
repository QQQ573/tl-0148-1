from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric, Text, Date, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
import enum

from app.core.database import Base


class UserRole(str, enum.Enum):
    WORKSHOP_MANAGER = "workshop_manager"
    MASTER = "master"
    FINANCE = "finance"
    STUDENT = "student"


class BookingStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_QUOTA = "pending_quota"
    PENDING_SIGNATURE = "pending_signature"
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ClayType(str, enum.Enum):
    GAOBAI_NI = "gaobai_ni"
    HONGTAO = "hongtao"
    XIANWEI_NI = "xianwei_ni"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True)
    role = Column(PGEnum(UserRole, name="user_role_enum", create_type=True), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    student_bookings = relationship("Booking", foreign_keys="Booking.student_id", back_populates="student")
    master_classes = relationship("MasterClass", foreign_keys="MasterClass.master_id", back_populates="master")
    signed_bookings = relationship("Booking", foreign_keys="Booking.signed_by_id", back_populates="signed_by")


class MasterClass(Base):
    __tablename__ = "master_classes"
    __table_args__ = (
        UniqueConstraint("year", "month", "class_no", name="uq_year_month_class_no"),
    )

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    master_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    class_date = Column(Date, nullable=False, index=True)
    start_time = Column(String(10), nullable=False)
    end_time = Column(String(10), nullable=False)
    capacity = Column(Integer, nullable=False, default=8)
    year = Column(Integer, nullable=False, index=True)
    month = Column(Integer, nullable=False, index=True)
    class_no = Column(Integer, nullable=False, index=True)
    is_published = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    master = relationship("User", back_populates="master_classes")
    bookings = relationship("Booking", back_populates="master_class")
    clay_quotas = relationship("ClayQuota", back_populates="master_class")


class ClayQuota(Base):
    __tablename__ = "clay_quotas"
    __table_args__ = (
        UniqueConstraint("master_class_id", "clay_type", name="uq_class_clay_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    master_class_id = Column(Integer, ForeignKey("master_classes.id"), nullable=False, index=True)
    clay_type = Column(PGEnum(ClayType, name="clay_type_enum", create_type=True), nullable=False)
    total_kg = Column(Numeric(10, 2), nullable=False)
    used_kg = Column(Numeric(10, 2), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    master_class = relationship("MasterClass", back_populates="clay_quotas")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_booking_student_month_status", "student_id", "class_year", "class_month", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    booking_no = Column(String(32), unique=True, index=True, nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    master_class_id = Column(Integer, ForeignKey("master_classes.id"), nullable=False, index=True)
    class_year = Column(Integer, nullable=False)
    class_month = Column(Integer, nullable=False)
    status = Column(PGEnum(BookingStatus, name="booking_status_enum", create_type=True), nullable=False, default=BookingStatus.DRAFT, index=True)
    gaobai_ni_kg = Column(Numeric(10, 2), nullable=False, default=0)
    hongtao_kg = Column(Numeric(10, 2), nullable=False, default=0)
    xianwei_ni_kg = Column(Numeric(10, 2), nullable=False, default=0)
    student_remark = Column(Text, nullable=True)
    quota_remark = Column(Text, nullable=True)
    reject_reason = Column(Text, nullable=True)
    signed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    signed_at = Column(DateTime, nullable=True)
    paid_amount = Column(Numeric(10, 2), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)
    last_alerted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    student = relationship("User", foreign_keys=[student_id], back_populates="student_bookings")
    signed_by = relationship("User", foreign_keys=[signed_by_id], back_populates="signed_bookings")
    master_class = relationship("MasterClass", back_populates="bookings")
    attachments = relationship("Attachment", back_populates="booking")
    status_logs = relationship("BookingStatusLog", back_populates="booking")


class BookingStatusLog(Base):
    __tablename__ = "booking_status_logs"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, index=True)
    from_status = Column(PGEnum(BookingStatus, name="booking_status_enum", create_type=True), nullable=True)
    to_status = Column(PGEnum(BookingStatus, name="booking_status_enum", create_type=True), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    booking = relationship("Booking", back_populates="status_logs")


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    minio_object_key = Column(String(500), nullable=False)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    booking = relationship("Booking", back_populates="attachments")
