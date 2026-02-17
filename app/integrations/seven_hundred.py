from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal
import xml.etree.ElementTree as ET

import requests

from app.models.prequal_result import PrequalResult


class SevenHundredCreditClient:
    TEST_GATEWAY = "https://gateway.700creditsolution.com"
    PROD_GATEWAY = "https://gateway.700dealer.com"

    def __init__(
        self,
        account: str,
        password: str,
        *,
        environment: Literal["test", "prod"] = "test",
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        self.account = account
        self.password = password
        self.timeout = timeout

        if environment == "prod":
            self.base_url = self.PROD_GATEWAY
        else:
            self.base_url = self.TEST_GATEWAY

        self.request_url = f"{self.base_url}/Request"
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    @classmethod
    def from_env(cls) -> "SevenHundredCreditClient":
        account = os.getenv("SEVENCREDIT_ACCOUNT")
        password = os.getenv("SEVENCREDIT_PASSWORD")
        if not account or not password:
            raise ValueError("SEVENCREDIT_ACCOUNT and SEVENCREDIT_PASSWORD are required")
        return cls(
            account=account,
            password=password,
            environment=os.getenv("SEVENCREDIT_ENV", "test"),
            client_id=os.getenv("SEVENCREDIT_CLIENT_ID"),
            client_secret=os.getenv("SEVENCREDIT_CLIENT_SECRET"),
        )

    def send_prequalify(
        self,
        *,
        first_name: str,
        last_name: str,
        address: str,
        city: str,
        state: str,
        zip_code: str,
        bureau: Literal["TU", "XPN", "EFX"] = "TU",
        ssn: Optional[str] = None,
        app_modified: bool = False,
        extra_fields: Optional[dict] = None,
    ) -> PrequalResult:
        name_value = f"{first_name} {last_name}"

        data = {
            "ACCOUNT": self.account,
            "PASSWD": self.password,
            "PASS": "2",
            "PROCESS": "PCCREDIT",
            "PRODUCT": "PREQUALIFY",
            "BUREAU": bureau,
            "NAME": name_value,
            "ADDRESS": address,
            "CITY": city,
            "STATE": state,
            "ZIP": zip_code,
        }

        if ssn:
            data["SSN"] = ssn
        if app_modified:
            data["APP_MODIFIED"] = "Y"
        if extra_fields:
            data.update(extra_fields)

        resp = requests.post(self.request_url, data=data, timeout=self.timeout)
        resp.raise_for_status()
        return self._parse_prequal_response(resp.text)

    def sign_iframe_url(
        self,
        unsigned_url: str,
        *,
        signed_by: str = "DealerApp",
        duration_minutes: int = 10,
    ) -> str:
        if not self.client_id or not self.client_secret:
            raise ValueError("client_id and client_secret must be provided to sign URLs.")
        if not unsigned_url:
            raise ValueError("unsigned_url is required.")
        if not isinstance(duration_minutes, int) or not (1 <= duration_minutes <= 30):
            raise ValueError("duration must be an integer between 1 and 30 minutes.")
        if not re.fullmatch(r"[A-Za-z0-9]+", signed_by):
            raise ValueError("signed_by must be alphanumeric only.")

        token = self._get_access_token()
        sign_url = f"{self.base_url}/.auth/sign"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "url": unsigned_url,
            "duration": duration_minutes,
            "signedBy": signed_by,
        }

        res = requests.post(sign_url, json=payload, headers=headers, timeout=self.timeout)
        res.raise_for_status()
        data = res.json()
        return data["url"]

    def _get_access_token(self) -> str:
        if self._access_token and self._token_expiry:
            if datetime.now(timezone.utc) < self._token_expiry - timedelta(minutes=1):
                return self._access_token

        token_url = f"{self.base_url}/.auth/token"
        payload = {"ClientId": self.client_id, "ClientSecret": self.client_secret}
        res = requests.post(token_url, json=payload, timeout=self.timeout)
        res.raise_for_status()
        data = res.json()

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        return self._access_token

    def _parse_prequal_response(self, xml_text: str) -> PrequalResult:
        result = PrequalResult(raw_xml=xml_text)
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return result

        error_el = root.find(".//Creditsystem_Error")
        if error_el is not None:
            result.result_code = error_el.get("id")
            result.result_description = error_el.get("message")
            return result

        xml_report = root.find(".//XML_Report")
        if xml_report is not None:
            transid_el = xml_report.find("Transid")
            token_el = xml_report.find("Token")
            if transid_el is not None:
                result.transid = transid_el.text or None
            if token_el is not None:
                result.token = token_el.text or None

        prescreen = root.find(".//Prescreen_Report")
        if prescreen is not None:
            rc = prescreen.find("ResultCode")
            rd = prescreen.find("ResultDescription")
            tier = prescreen.find("Tier")
            score = prescreen.find("Score")
            score_range = prescreen.find("ScoreRange")

            if rc is not None:
                result.result_code = rc.text or None
            if rd is not None:
                result.result_description = rd.text or None
            if tier is not None:
                result.tier = tier.text or None
            if score is not None and (score.text or "").strip().isdigit():
                result.score = int(score.text.strip())
            if score_range is not None:
                result.score_range = score_range.text or None

        custom_report = root.find(".//custom_report")
        if custom_report is not None and custom_report.text:
            text = custom_report.text
            marker_idx = text.lower().find('src="')
            if marker_idx != -1:
                start = marker_idx + len('SRC="')
                end = text.find('"', start)
                if end != -1:
                    result.iframe_url = text[start:end]

        return result
