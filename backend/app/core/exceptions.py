from fastapi import HTTPException


class DocumentNotFoundError(HTTPException):
    def __init__(self, document_id: str) -> None:
        super().__init__(status_code=404, detail=f"Document {document_id} not found")


class DocumentProcessingError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, detail=detail)


class InvalidFileError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=400, detail=detail)


class ExternalServiceError(HTTPException):
    def __init__(self, service: str) -> None:
        super().__init__(status_code=503, detail=f"{service} service unavailable")
