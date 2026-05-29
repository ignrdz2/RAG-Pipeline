# TODO: implement POST /documents/upload, GET /documents, GET /documents/{id}, DELETE /documents/{id}
from fastapi import APIRouter

router = APIRouter(prefix="/documents", tags=["documents"])
