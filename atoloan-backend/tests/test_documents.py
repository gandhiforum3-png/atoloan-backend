"""
Unit tests for the /uploadDocuments endpoint and document-key persistence.

Covers:
  1. _save_document_keys() service — keys saved on the loan application (mocked AsyncConnection)
  2. POST /me/applications/{id}/documents — session + ownership required,
     content sniffing, server-built S3 keys, one or both files, S3 failures
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
        "drivers_license": ("license.jpg", JPEG, "image/jpeg"),
        "paycheck": ("paycheck.pdf", PDF, "application/pdf"),
    }


JPEG = b"\xff\xd8\xff\xe0fake jpeg bytes"
PDF = b"%PDF-1.7 fake pdf bytes"
URL = "/me/applications/42/documents"


def _mock_owned(monkeypatch, owned: bool = True) -> AsyncMock:
    """Stands in for the ownership lookup: application 42 belongs to the
    signed-in test customer (jane@example.com) unless owned=False."""
    mock = AsyncMock(return_value=owned)
    monkeypatch.setattr(documents_module, "_owns_application", mock)
    return mock


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
            application_id=42,
            uploaded_files=[
                {"field": "drivers_license", "key": "sub1/dl.jpg"},
                {"field": "paycheck", "key": "sub1/pc.jpg"},
            ],
        )

        conn.execute.assert_awaited_once()
        params = conn.execute.call_args.args[1]
        assert params["id"] == 42
        assert "loan_applications" in str(conn.execute.call_args.args[0])
        assert params["drivers_license_key"] == "sub1/dl.jpg"
        assert params["paycheck_key"] == "sub1/pc.jpg"

    async def test_partial_upload_only_sets_provided_key(self, monkeypatch) -> None:
        """Uploading just one file must not touch the other key column's value."""
        engine, conn = self._make_conn()
        monkeypatch.setattr(documents_module, "get_engine", lambda: engine)

        await _save_document_keys(
            application_id=42,
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

        await _save_document_keys(application_id=42, uploaded_files=[])

        conn.execute.assert_not_awaited()

    async def test_db_failure_is_raised(self, monkeypatch) -> None:
        """A key that wasn't recorded must not be reported as received."""
        engine, conn = self._make_conn()
        conn.execute = AsyncMock(side_effect=RuntimeError("DB is down"))
        monkeypatch.setattr(documents_module, "get_engine", lambda: engine)

        with pytest.raises(RuntimeError):
            await _save_document_keys(application_id=42, uploaded_files=[{"field": "paycheck", "key": "sub1/pc.jpg"}])


# ---------------------------------------------------------------------------
# 2. POST /me/applications/{id}/documents
# ---------------------------------------------------------------------------

class TestApplicationDocumentsRouter:
    @pytest.mark.anonymous_customer
    def test_upload_requires_session(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        s3 = _mock_s3_client(monkeypatch)

        resp = _client().post(URL, files=_files())

        assert resp.status_code == 401
        s3.put_object.assert_not_called()

    def test_upload_to_someone_elses_application_is_404(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        s3 = _mock_s3_client(monkeypatch)
        owned = _mock_owned(monkeypatch, owned=False)

        resp = _client().post(URL, files=_files())

        assert resp.status_code == 404
        s3.put_object.assert_not_called()
        owned.assert_awaited_once_with(42, "jane@example.com")

    def test_form_cannot_choose_the_application(self, monkeypatch) -> None:
        """Only the URL's application, checked against the session, is used."""
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)
        _mock_owned(monkeypatch)
        save_mock = _mock_save_document_keys(monkeypatch)

        _client().post(URL, data={"application_id": "99", "user_email": "victim@example.com"}, files=_files())

        assert save_mock.call_args.kwargs["application_id"] == 42

    def test_rejects_non_document_content(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        s3 = _mock_s3_client(monkeypatch)
        _mock_owned(monkeypatch)

        files = {
            "drivers_license": ("license.jpg", b"<html>not an image</html>", "image/jpeg"),
            "paycheck": ("../../evil.pdf", b"MZ\x90 exe", "application/pdf"),
        }
        resp = _client().post(URL, files=files)

        assert resp.status_code == 400
        s3.put_object.assert_not_called()

    def test_s3_key_ignores_client_filename(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        s3 = _mock_s3_client(monkeypatch)
        _mock_owned(monkeypatch)
        _mock_save_document_keys(monkeypatch)

        files = {"drivers_license": ("../../etc/passwd.jpg", JPEG, "text/html"), "paycheck": ("p.pdf", PDF, "application/pdf")}
        _client().post(URL, files=files)

        put = s3.put_object.call_args_list[0].kwargs
        assert put["Key"] == "applications/42/drivers_license"
        assert put["ContentType"] == "image/jpeg"

    def test_replacing_a_document_overwrites_the_same_object(self, monkeypatch) -> None:
        """One key per application + document: a replacement becomes a new version
        of the same object (expired by the bucket lifecycle), not a second file
        kept forever — the app's S3 role is write-only and can't delete."""
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        s3 = _mock_s3_client(monkeypatch)
        _mock_owned(monkeypatch)
        _mock_save_document_keys(monkeypatch)

        _client().post(URL, files={"paycheck": ("p.pdf", PDF, "application/pdf")})
        _client().post(URL, files={"paycheck": ("p.png", b"\x89PNG\r\n\x1a\nfake", "image/png")})

        keys = [call.kwargs["Key"] for call in s3.put_object.call_args_list]
        assert keys == ["applications/42/paycheck", "applications/42/paycheck"]

    def test_no_files_returns_400(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)
        _mock_owned(monkeypatch)

        resp = _client().post(URL, data={"note": "nothing attached"})

        assert resp.status_code == 400

    def test_successful_upload_returns_s3_keys(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)
        _mock_owned(monkeypatch)
        save_mock = _mock_save_document_keys(monkeypatch)

        resp = _client().post(URL, files=_files())

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert {f["field"] for f in body["files"]} == {"drivers_license", "paycheck"}
        for f in body["files"]:
            assert "key" in f
            assert "path" not in f  # regression guard: must not return local filesystem paths
        save_mock.assert_awaited_once()

    def test_single_file_replaces_only_that_document(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)
        _mock_owned(monkeypatch)
        save_mock = _mock_save_document_keys(monkeypatch)

        resp = _client().post(URL, files={"paycheck": ("p.pdf", PDF, "application/pdf")})

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert [f["field"] for f in save_mock.call_args.kwargs["uploaded_files"]] == ["paycheck"]

    def test_partial_when_one_provided_file_is_invalid(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)
        _mock_owned(monkeypatch)
        _mock_save_document_keys(monkeypatch)

        files = {"drivers_license": ("license.jpg", JPEG, "image/jpeg"), "paycheck": ("p.txt", b"plain text", "text/plain")}
        resp = _client().post(URL, files=files)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "partial"
        assert [f["field"] for f in body["files"]] == ["drivers_license"]
        assert "paycheck must be a PDF, JPEG, PNG or HEIC file" in body["errors"]

    def test_s3_failure_on_both_files_returns_400(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_owned(monkeypatch)
        failing_put = MagicMock(
            side_effect=ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "PutObject")
        )
        _mock_s3_client(monkeypatch, put_object=failing_put)
        save_mock = _mock_save_document_keys(monkeypatch)

        resp = _client().post(URL, files=_files())

        assert resp.status_code == 400
        save_mock.assert_not_awaited()

    def test_missing_bucket_config_returns_500(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_owned(monkeypatch)
        settings = MagicMock(s3_bucket_name="", aws_region="us-east-2")
        monkeypatch.setattr(documents_module, "get_settings", lambda: settings)

        resp = _client().post(URL, files=_files())

        assert resp.status_code == 500

    def test_unrecorded_upload_is_an_error_not_success(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        _mock_settings(monkeypatch)
        _mock_s3_client(monkeypatch)
        _mock_owned(monkeypatch)
        monkeypatch.setattr(documents_module, "_save_document_keys", AsyncMock(side_effect=RuntimeError("db down")))

        resp = _client().post(URL, files=_files())

        assert resp.status_code == 503
        assert "try again" in resp.json()["detail"]

    def test_old_token_upload_route_is_gone(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        assert _client().post("/uploadDocuments", files=_files()).status_code in (404, 405)
