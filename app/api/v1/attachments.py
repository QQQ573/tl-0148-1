from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Form
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.user import UserRole
from app.services.attachment_service import AttachmentService
from app.services.booking_service import BookingService
from app.schemas.user import AttachmentResponse, ApiResponse

router = APIRouter(prefix="/attachments", tags=["附件管理"])


def _enrich_attachment(att, url: Optional[str] = None) -> AttachmentResponse:
    data = AttachmentResponse.model_validate(att)
    data.download_url = url
    return data


@router.post("/upload", response_model=ApiResponse[AttachmentResponse])
async def upload_attachment(
    booking_id: int = Form(...),
    file: UploadFile = File(...),
    current_user=Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    content = await file.read()
    size = len(content)
    if size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="附件大小不能超过10MB")
    import io
    try:
        att = await AttachmentService.upload_attachment(
            db, booking_id=booking_id, uploader_id=current_user.id,
            filename=file.filename, file_data=io.BytesIO(content),
            content_type=file.content_type, file_size=size,
        )
        url = await AttachmentService.get_download_url(db, att.id)
        return ApiResponse(data=_enrich_attachment(att, url))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/booking/{booking_id}", response_model=ApiResponse[list[AttachmentResponse]])
async def list_booking_attachments(
    booking_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bk = await BookingService.get_booking(db, booking_id)
    if not bk:
        raise HTTPException(status_code=404, detail="预约单不存在")
    if current_user.role == UserRole.STUDENT and bk.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看")
    attachments = await AttachmentService.list_attachments(db, booking_id)
    result = []
    for att in attachments:
        url = await AttachmentService.get_download_url(db, att.id)
        result.append(_enrich_attachment(att, url))
    return ApiResponse(data=result)


@router.get("/{attachment_id}/download-url", response_model=ApiResponse[AttachmentResponse])
async def get_download_url(
    attachment_id: int,
    expires_hours: int = 1,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    att = await AttachmentService.get_attachment(db, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="附件不存在")
    bk = await BookingService.get_booking(db, att.booking_id)
    if not bk:
        raise HTTPException(status_code=404, detail="预约单不存在")
    if current_user.role == UserRole.STUDENT and bk.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权下载")
    url = await AttachmentService.get_download_url(db, attachment_id, expires_hours=expires_hours)
    return ApiResponse(data=_enrich_attachment(att, url))


@router.delete("/{attachment_id}", response_model=ApiResponse)
async def delete_attachment(
    attachment_id: int,
    current_user=Depends(require_roles("student", "workshop_manager")),
    db: AsyncSession = Depends(get_db),
):
    await AttachmentService.delete_attachment(db, attachment_id, current_user.id)
    return ApiResponse(message="删除成功")
