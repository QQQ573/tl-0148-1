import uuid
from typing import List, Optional, BinaryIO
from datetime import timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import Attachment, Booking
from app.core.exceptions import ResourceNotFoundError, BusinessError
from app.core.minio_client import MinioClient
from app.services.booking_service import BookingService


class AttachmentService:
    @staticmethod
    def _generate_object_key(booking_id: int, original_name: str) -> str:
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        rand = uuid.uuid4().hex[:12]
        ts_part = uuid.uuid4().hex[:6]
        return f"bookings/{booking_id}/{ts_part}_{rand}.{ext}" if ext else f"bookings/{booking_id}/{ts_part}_{rand}"

    @staticmethod
    async def upload_attachment(
        db: AsyncSession,
        booking_id: int,
        uploader_id: int,
        filename: str,
        file_data: BinaryIO,
        content_type: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> Attachment:
        booking = await BookingService.get_booking_or_404(db, booking_id)
        if booking.student_id != uploader_id:
            raise BusinessError("只能为自己的预约单上传附件")

        object_key = AttachmentService._generate_object_key(booking_id, filename)
        MinioClient.ensure_bucket()
        actual_size = file_size if file_size else 0
        MinioClient.upload_file(
            object_name=object_key,
            file_data=file_data,
            length=actual_size,
            content_type=content_type or "application/octet-stream",
        )

        stored_name = object_key.split("/")[-1]
        att = Attachment(
            booking_id=booking_id,
            file_name=stored_name,
            original_name=filename,
            content_type=content_type,
            file_size=file_size,
            minio_object_key=object_key,
            uploaded_by_id=uploader_id,
        )
        db.add(att)
        await db.commit()
        await db.refresh(att)
        return att

    @staticmethod
    async def list_attachments(db: AsyncSession, booking_id: int) -> List[Attachment]:
        result = await db.execute(
            select(Attachment).where(Attachment.booking_id == booking_id).order_by(Attachment.id.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_attachment(db: AsyncSession, attachment_id: int) -> Optional[Attachment]:
        result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_attachment_or_404(db: AsyncSession, attachment_id: int) -> Attachment:
        att = await AttachmentService.get_attachment(db, attachment_id)
        if not att:
            raise ResourceNotFoundError("附件", attachment_id)
        return att

    @staticmethod
    async def get_download_url(db: AsyncSession, attachment_id: int, expires_hours: int = 1) -> str:
        att = await AttachmentService.get_attachment_or_404(db, attachment_id)
        url = MinioClient.get_presigned_url(
            object_name=att.minio_object_key,
            expires=timedelta(hours=expires_hours),
        )
        return url

    @staticmethod
    async def delete_attachment(db: AsyncSession, attachment_id: int, operator_id: int) -> None:
        att = await AttachmentService.get_attachment_or_404(db, attachment_id)
        try:
            MinioClient.remove_file(att.minio_object_key)
        except Exception:
            pass
        await db.delete(att)
        await db.commit()
