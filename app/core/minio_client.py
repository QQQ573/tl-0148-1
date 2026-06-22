from typing import Optional, BinaryIO
from datetime import timedelta
from minio import Minio
from minio.error import S3Error

from app.core.config import settings


class MinioClient:
    _client: Optional[Minio] = None

    @classmethod
    def get_client(cls) -> Minio:
        if cls._client is None:
            cls._client = Minio(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ROOT_USER,
                secret_key=settings.MINIO_ROOT_PASSWORD,
                secure=settings.MINIO_SECURE,
            )
        return cls._client

    @classmethod
    def ensure_bucket(cls) -> None:
        client = cls.get_client()
        try:
            if not client.bucket_exists(settings.MINIO_BUCKET):
                client.make_bucket(settings.MINIO_BUCKET)
        except S3Error:
            pass

    @classmethod
    def upload_file(
        cls,
        object_name: str,
        file_data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> None:
        client = cls.get_client()
        client.put_object(
            bucket_name=settings.MINIO_BUCKET,
            object_name=object_name,
            data=file_data,
            length=length,
            content_type=content_type,
        )

    @classmethod
    def get_presigned_url(
        cls,
        object_name: str,
        expires: timedelta = timedelta(hours=1),
    ) -> str:
        client = cls.get_client()
        return client.presigned_get_object(
            bucket_name=settings.MINIO_BUCKET,
            object_name=object_name,
            expires=expires,
        )

    @classmethod
    def remove_file(cls, object_name: str) -> None:
        client = cls.get_client()
        client.remove_object(settings.MINIO_BUCKET, object_name)
