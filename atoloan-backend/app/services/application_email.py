"""
Builds and sends the loan-application summary email to the applicant after
a successful /findback submission — soft-pull credit score, matched bank,
and its available rate for each loan term.
"""
import logging

from app.core.config import get_settings
from app.integrations.ses_email import send_email

logger = logging.getLogger(__name__)


def send_application_summary_email(
    *,
    to_address: str,
    first_name: str,
    credit_score: int | None,
    best_offer: dict | None,
) -> None:
    """
    Best-effort by convention of the caller: this raises on any SES error
    (see app.integrations.ses_email.send_email) so callers running it as a
    background task can catch/log without failing the original request.
    """
    settings = get_settings()
    text_body, html_body = _render(first_name, credit_score, best_offer)

    send_email(
        region=settings.aws_region,
        sender=settings.ses_sender_email,
        to_address=to_address,
        subject="Your ATOLoan Pre-Qualification Results",
        html_body=html_body,
        text_body=text_body,
    )
    logger.info("Sent application summary email to %s", to_address)


def _render(first_name: str, credit_score: int | None, best_offer: dict | None) -> tuple[str, str]:
    score_line = str(credit_score) if credit_score else "Unavailable"

    if best_offer:
        rows = best_offer.get("term_options") or [{
            "term_in_months": best_offer.get("term_in_months"),
            "interest_rate": best_offer.get("interest_rate"),
        }]
        text_rows = "\n".join(
            f"  {r['term_in_months']} months: {r['interest_rate']}" for r in rows
        )
        html_rows = "\n".join(
            f"<tr><td style=\"padding:4px 12px;border:1px solid #ddd;\">{r['term_in_months']} months</td>"
            f"<td style=\"padding:4px 12px;border:1px solid #ddd;\">{r['interest_rate']}</td></tr>"
            for r in rows
        )
        bank_name = best_offer.get("bank_name", "N/A")
        program_name = best_offer.get("program_name", "")

        text_body = f"""Hi {first_name},

Thanks for submitting your ATOLoan application. Here is a summary of your pre-qualification results.

Estimated Credit Score: {score_line}

Matched Lender: {bank_name}
Program: {program_name}

Available Rates by Term:
{text_rows}

These are estimated rates based on the information you provided and are not a final loan offer. A member of our team will follow up with next steps.

— The ATOLoan Team
"""
        html_body = f"""<html><body style="font-family:Arial,sans-serif;color:#333;">
<p>Hi {first_name},</p>
<p>Thanks for submitting your ATOLoan application. Here is a summary of your pre-qualification results.</p>
<p><strong>Estimated Credit Score:</strong> {score_line}</p>
<p><strong>Matched Lender:</strong> {bank_name}<br/>
<strong>Program:</strong> {program_name}</p>
<p><strong>Available Rates by Term:</strong></p>
<table style="border-collapse:collapse;">
<tr><th style="padding:4px 12px;border:1px solid #ddd;text-align:left;">Term</th><th style="padding:4px 12px;border:1px solid #ddd;text-align:left;">Rate</th></tr>
{html_rows}
</table>
<p style="color:#777;font-size:12px;">These are estimated rates based on the information you provided and are not a final loan offer. A member of our team will follow up with next steps.</p>
<p>— The ATOLoan Team</p>
</body></html>
"""
    else:
        text_body = f"""Hi {first_name},

Thanks for submitting your ATOLoan application.

Estimated Credit Score: {score_line}

We weren't able to automatically match you to a lender based on the information provided — a member of our team will follow up with you directly.

— The ATOLoan Team
"""
        html_body = f"""<html><body style="font-family:Arial,sans-serif;color:#333;">
<p>Hi {first_name},</p>
<p>Thanks for submitting your ATOLoan application.</p>
<p><strong>Estimated Credit Score:</strong> {score_line}</p>
<p>We weren't able to automatically match you to a lender based on the information provided — a member of our team will follow up with you directly.</p>
<p>— The ATOLoan Team</p>
</body></html>
"""

    return text_body, html_body
