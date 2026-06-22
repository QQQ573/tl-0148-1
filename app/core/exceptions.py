from fastapi import HTTPException, status


class AppError(Exception):
    def __init__(self, code: int, message: str, data: dict | None = None):
        self.code = code
        self.message = message
        self.data = data or {}


class ResourceNotFoundError(AppError):
    def __init__(self, resource: str, resource_id: str | int | None = None):
        msg = f"{resource}不存在"
        if resource_id is not None:
            msg = f"{resource} (ID={resource_id}) 不存在"
        super().__init__(code=404, message=msg)


class BusinessError(AppError):
    def __init__(self, message: str, data: dict | None = None):
        super().__init__(code=400, message=message, data=data)


class VersionConflictError(AppError):
    def __init__(self, current_version: int, message: str = "数据已被其他操作修改，请刷新后重试"):
        super().__init__(code=409, message=message, data={"current_version": current_version})


def raise_http_error(error: AppError):
    raise HTTPException(status_code=error.code if error.code < 600 else 400, detail=error.message, headers={"X-Error-Code": str(error.code)})
