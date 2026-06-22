from datetime import datetime, date
from typing import Optional, List, Dict, Any
from decimal import Decimal
from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.models.user import UserRole, BookingStatus, ClayType


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: Optional[str] = None


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    role: UserRole


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=100)


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    full_name: str
    phone: Optional[str]
    role: UserRole
    is_active: bool
    created_at: datetime


class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page: int
    page_size: int


class ClayQuotaBase(BaseModel):
    clay_type: ClayType
    total_kg: Decimal = Field(..., gt=0, max_digits=10, decimal_places=2)


class ClayQuotaCreate(ClayQuotaBase):
    pass


class ClayQuotaUpdate(BaseModel):
    total_kg: Optional[Decimal] = Field(None, gt=0, max_digits=10, decimal_places=2)
    used_kg: Optional[Decimal] = Field(None, ge=0, max_digits=10, decimal_places=2)


class ClayQuotaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    master_class_id: int
    clay_type: ClayType
    total_kg: Decimal
    used_kg: Decimal
    remaining_kg: Optional[Decimal] = None


class MasterClassBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = None
    master_id: int
    class_date: date
    start_time: str = Field(..., pattern=r'^\d{2}:\d{2}$')
    end_time: str = Field(..., pattern=r'^\d{2}:\d{2}$')
    capacity: int = Field(..., ge=1, le=50)
    year: int
    month: int = Field(..., ge=1, le=12)
    class_no: int = Field(..., ge=1, le=31)
    is_published: bool = False


class MasterClassCreate(MasterClassBase):
    clay_quotas: List[ClayQuotaCreate] = Field(..., min_length=1)


class MasterClassUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    master_id: Optional[int] = None
    class_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    capacity: Optional[int] = None
    is_published: Optional[bool] = None
    clay_quotas: Optional[List[ClayQuotaUpdate]] = None


class MasterClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: Optional[str]
    master_id: int
    master_name: Optional[str] = None
    class_date: date
    start_time: str
    end_time: str
    capacity: int
    year: int
    month: int
    class_no: int
    is_published: bool
    clay_quotas: List[ClayQuotaResponse] = []
    created_at: datetime


class MasterClassListResponse(BaseModel):
    items: List[MasterClassResponse]
    total: int
    page: int
    page_size: int


class BookingCreate(BaseModel):
    master_class_id: int
    gaobai_ni_kg: Decimal = Field(0, ge=0, max_digits=10, decimal_places=2)
    hongtao_kg: Decimal = Field(0, ge=0, max_digits=10, decimal_places=2)
    xianwei_ni_kg: Decimal = Field(0, ge=0, max_digits=10, decimal_places=2)
    student_remark: Optional[str] = None


class BookingUpdateStatus(BaseModel):
    version: int = Field(..., ge=1)
    remark: Optional[str] = None
    reject_reason: Optional[str] = None
    paid_amount: Optional[Decimal] = None


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    booking_no: str
    student_id: int
    student_name: Optional[str] = None
    master_class_id: int
    class_title: Optional[str] = None
    class_date: Optional[date] = None
    class_year: int
    class_month: int
    status: BookingStatus
    gaobai_ni_kg: Decimal
    hongtao_kg: Decimal
    xianwei_ni_kg: Decimal
    student_remark: Optional[str]
    quota_remark: Optional[str]
    reject_reason: Optional[str]
    signed_by_id: Optional[int]
    signed_by_name: Optional[str] = None
    signed_at: Optional[datetime]
    paid_amount: Optional[Decimal]
    paid_at: Optional[datetime]
    version: int
    last_updated_at: datetime
    created_at: datetime


class BookingListResponse(BaseModel):
    items: List[BookingResponse]
    total: int
    page: int
    page_size: int


class BookingVersionConflictResponse(BaseModel):
    detail: str
    current_version: int


class QuotaCheckItem(BaseModel):
    clay_type: ClayType
    requested_kg: Decimal
    remaining_kg: Decimal
    sufficient: bool


class QuotaCheckResponse(BaseModel):
    sufficient: bool
    details: List[QuotaCheckItem]
    recommended_classes: List[MasterClassResponse] = []


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    booking_id: int
    file_name: str
    original_name: str
    content_type: Optional[str]
    file_size: Optional[int]
    download_url: Optional[str] = None
    created_at: datetime


class StatusLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    booking_id: int
    from_status: Optional[BookingStatus]
    to_status: BookingStatus
    operator_id: Optional[int]
    operator_name: Optional[str] = None
    remark: Optional[str]
    created_at: datetime


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Optional[Any] = None
