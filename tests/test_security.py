import io

import pytest
from starlette.datastructures import UploadFile

from app.security import hash_password, validate_docx_upload, verify_bearer_value, verify_password


def test_password_hash_verify():
    password_hash = hash_password("secret")
    assert verify_password("secret", password_hash)
    assert not verify_password("bad", password_hash)


def test_bearer_token_check():
    assert verify_bearer_value("Bearer abc", "abc")
    assert not verify_bearer_value("Bearer abc", "def")


@pytest.mark.asyncio
async def test_docx_upload_validation_rejects_extension():
    upload = UploadFile(filename="bad.txt", file=io.BytesIO(b"PKfake"))
    with pytest.raises(Exception):
        await validate_docx_upload(upload, 1)


@pytest.mark.asyncio
async def test_docx_upload_validation_accepts_docx_like_zip():
    upload = UploadFile(filename="ok.docx", file=io.BytesIO(b"PKfake"))
    assert await validate_docx_upload(upload, 1) == b"PKfake"

