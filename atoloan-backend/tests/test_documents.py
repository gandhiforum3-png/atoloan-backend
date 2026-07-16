"""
Unit tests for the /uploadDocuments endpoint and document-key persistence.

Covers:
  1. _save_document_keys() service — DB upsert via mocked AsyncConnection
  2. /uploadDocuments router — user_email required
  3. /uploadDocuments router — successful upload returns S3 keys (not local paths)
  4. /uploadDocuments router — partial upload (one file only) still succeeds
  5. /uploadDocuments router — S3 failure on both files returns 400
  6. /uploadDocuments router — _save_document_keys is called with the right keys
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import app.main as main
from app.api.routers import documents as documents_module
from app.api.routers.documents import _save_document_keys


def _client() -> TestClient:
    return TestClient(main.app)


async def _noop() -> None:
    return None


def _disable_db_checks(monkeypatch) -> None:
    monkeypatch.setattr(main, "create_tables", _noop)
    monkeypatch.setattr(main, "test_connection", _noop)


def _mock_settings(monkeypatch) -> None:
    settings = MagicMock(s3_bucket_name="test-bucket", aws_region="us-east-2")
    monkeypatch.setattr(documents_module, "get_settings", lambda: settings)


def _mock_s3_client(monkeypatch, put_object=None) -> MagicMock:
    """Mocks boto3.client("s3", ...) as used inside the documents router."""
    s3_client = MagicMock()
    if put_object is not None:
        s3_client.put_object = put_object
    monkeypatch.setattr(documents_module.boto3, "client", lambda *_, **__: s3_client)
    return s3_client


def _mock_save_document_keys(monkeypatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(documents_module, "_save_document_keys", mock)
    return mock


def _files() -> dict:
    return {
        "drivers_license": ("license.jpg", b"fake license bytes", "image/jpeg"),
        "paycheck": ("paycheck.jpg", b"fake paycheck bytes", "image/jpeg"),
    }


def _form(**overrides) -> dict:
    form = {
        "user_email": "jane@example.com",
        "first_name": "Jane",
        "last_name": "Doe",
        "user_name": "Jane_Doe",
    }
    form.update(overrides)
    return form


# ---------------------------------------------------------------------------
# 1. _save_document_keys — unit tests (mocked AsyncConnection)
# ---------------------------------------------------------------------------

class TestSaveDocumentKeys:
    def _make_conn(self) -> AsyncMock:
        conn = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        engine = MagicMock()
        engine.begin.return_value = cm
        return engine, conn

    async def test_upserts_both_keys(self, monkeypatch) -> None:
        engine, conn = self._make_conn()
        monkeypatch.setattr(documents_module, "get_engine", lambda: engine)

        await _save_document_keys(
            user_email="jane@example.com",
            first_name="Jane",
            last_name="Doe",
            uploaded_files=[
                {"field": "drivers_license", "key": "sub1/dl.jpg"},
                {"field": "paycheck", "key": "sub1/pc.jpg"},
            ],
        )

        conn.execute.assert_awaited_once()
        params = conn.execute.call_args.args[1]
        assert params["email"] == "jane@example.com"
        assert params["drivers_license_key"] == "sub1/dl.jpg"
        assert params["paycheck_key"] == "sub1/pc.jpg"

    async def test_partial_upload_only_sets_provided_key(self, monkeypatch) -> None:
        """Uploading just one file must not touch the other key column's value."""
        engine, conn = self._make_conn()
        monkeypatch.setattr(documents_module, "get_engine", lambda: engine)

        await _save_document_keys(
            user_email="jane@example.com",
            first_name="Jane",
            last_name="Doe",
            uploaded_files=[{"field": "drivers_license", "key": "sub1/dl.jpg"}],
        )

        params = conn.execute.call_args.args[1]
        assert params["drivers_license_key"] == "sub1/dl.jpg"
        assert params["paycheck_key"] is None
        # The SQL itself must COALESCE so a NULL param doesn't clobber existing data.
        stmt = conn.execute.call_args.args[0]
        assert "COALESCE" in str(stmt)

    async def test_no_uploaded_files_is_noop(self, monkeypatch) -> None:
        engine, conn = self._make_conn()
        monkeypatch.setattr(documents_module, "get_engine", lambda: engine)

        await _save_document_keys(
            user_email="jane@example.com", first_name="Jane", last_name="Doe", uploaded_files=[]
        )

        conn.execute.assert_not_awaited()

    async def test_db_failure_does_not_raise(self, monkeypatch) -> None:
        """DB errors must be swallowed — the S3 upload already succeeded."""
        engine, conn = self._make_conn()
        conn.execute = AsyncMock(side_effect=RuntimeError("DB is down"))
        monkeypatch.setattr(documents_module, "get_engine", lambda: engine)

        await _save_document_keys(
            user_email="jane@example.com",
            first_name="Jane",
            last_name="Doe",
            uploaded_files=[{"field": "paycheck", "key": "sub1/pc.jpg"}],
        )  # must not raise


# ---------------------------------------------------------------------------
# 2. /uploadDocuments router
# ---------------------------------------------------------------------------

class TestUploadDocumentsRouter:
    def test_missing_email_returns_400(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)

        resp = _client().post("/uploadDocuments", data=_form(user_email=""), files=_files())

        assert resp.status_code == 400
        assert "user_email" in resp.json()["detail"]

    def test_missing_files_returns_400(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)

        resp = _client().post("/uploadDocuments", data=_form())

        assert resp.status_code == 400

    def test_successful_upload_returns_s3_keys(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)
        save_mock = _mock_save_document_keys(monkeypatch)

        resp = _client().post("/uploadDocuments", data=_form(), files=_files())

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert len(body["files"]) == 2
        for f in body["files"]:
            assert "key" in f
            assert "path" not in f  # regression guard: must not return local filesystem paths
        save_mock.assert_awaited_once()

    def test_save_document_keys_called_with_uploaded_keys(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)
        save_mock = _mock_save_document_keys(monkeypatch)

        _client().post("/uploadDocuments", data=_form(), files=_files())

        kwargs = save_mock.call_args.kwargs
        assert kwargs["user_email"] == "jane@example.com"
        assert kwargs["first_name"] == "Jane"
        assert kwargs["last_name"] == "Doe"
        fields = {f["field"] for f in kwargs["uploaded_files"]}
        assert fields == {"drivers_license", "paycheck"}

    def test_partial_upload_when_one_file_missing(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)
        _mock_save_document_keys(monkeypatch)

        files = {"drivers_license": ("license.jpg", b"fake bytes", "image/jpeg")}
        resp = _client().post("/uploadDocuments", data=_form(), files=files)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "partial"
        assert len(body["files"]) == 1
        assert "paycheck file is required" in body["errors"][0]

    def test_s3_failure_on_both_files_returns_400(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        failing_put = MagicMock(
            side_effect=ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "PutObject")
        )
        _mock_s3_client(monkeypatch, put_object=failing_put)
        save_mock = _mock_save_document_keys(monkeypatch)

        resp = _client().post("/uploadDocuments", data=_form(), files=_files())

        assert resp.status_code == 400
        save_mock.assert_not_awaited()

    def test_missing_bucket_config_returns_500(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        settings = MagicMock(s3_bucket_name="", aws_region="us-east-2")
        monkeypatch.setattr(documents_module, "get_settings", lambda: settings)

        resp = _client().post("/uploadDocuments", data=_form(), files=_files())

        assert resp.status_code == 500
