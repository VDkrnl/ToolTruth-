import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_REGION = os.getenv("AWS_REGION", "ap-south-1")
LOCAL_MODE = not S3_BUCKET or os.getenv("LOCAL_STORAGE", "false").lower() == "true"
LOCAL_ROOT = Path(__file__).resolve().parent / "uploads"
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _local_save(fileobj, key: str) -> None:
    dest = LOCAL_ROOT / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(fileobj.read())


def _local_url(key: str) -> str:
    return f"{PUBLIC_API_URL}/files/serve/{key}"


def _s3_client():
    import boto3
    return boto3.client("s3", region_name=S3_REGION)


def _s3_upload(fileobj, key: str, content_type: str) -> None:
    _s3_client().upload_fileobj(
        fileobj,
        S3_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def _s3_presigned(key: str, expires: int = 600) -> str:
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires,
    )


def make_key(filename: str) -> str:
    safe_name = Path(filename).name
    return f"deliverables/{uuid.uuid4().hex}/{safe_name}"


def upload_fileobj(fileobj, key: str, content_type: str) -> None:
    if LOCAL_MODE:
        _local_save(fileobj, key)
    else:
        if not S3_BUCKET:
            raise RuntimeError("S3_BUCKET is not configured")
        _s3_upload(fileobj, key, content_type)


def presigned_url(key: str, expires: int = 600) -> str:
    if LOCAL_MODE:
        return _local_url(key)
    return _s3_presigned(key, expires)


def delete_file(key: str) -> None:
    if LOCAL_MODE:
        path = LOCAL_ROOT / key
        if path.exists():
            path.unlink()
    else:
        if not S3_BUCKET:
            raise RuntimeError("S3_BUCKET is not configured")
        _s3_client().delete_object(
            Bucket=S3_BUCKET,
            Key=key,
        )