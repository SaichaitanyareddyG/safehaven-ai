"""Account emails: invite and password-reset links, sent through Resend's
HTTP API (an HTTPS call, not SMTP, which free hosts often block).

Never carries patient information — only a person's own name and a link.
Failures are returned, not raised: the admin can always copy the link
instead, so a mail outage never stops anyone getting an account.
"""

import logging
from dataclasses import dataclass
from html import escape

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class EmailResult:
    sent: bool
    # Short and safe to show an admin; never the provider's raw response.
    problem: str | None = None


def send_email(to: str, subject: str, text: str, html: str) -> EmailResult:
    settings = get_settings()
    if not settings.resend_api_key:
        return EmailResult(sent=False, problem="Email is not set up on this server")
    try:
        response = httpx.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.email_from, "to": [to], "subject": subject, "text": text, "html": html},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        logger.warning("Account email not sent: %s", type(exc).__name__)
        return EmailResult(sent=False, problem="The email service could not be reached")
    if response.status_code >= 300:
        # Status only: the body can echo the recipient address.
        logger.warning("Account email rejected by the provider: HTTP %s", response.status_code)
        if response.status_code == 403:
            return EmailResult(
                sent=False, problem="The email service can only send to the account owner until a domain is added"
            )
        return EmailResult(sent=False, problem="The email service refused the message")
    return EmailResult(sent=True)


FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def _layout(
    *,
    preheader: str,
    heading: str,
    paragraphs: list[str],
    button: str,
    link: str,
    note: str,
    reason: str,
    product: str = "Ward safety dashboard",
) -> str:
    """One branded, table-based email (what Gmail, Outlook and Apple Mail all
    render alike): dark teal header with the SafeHaven mark, a big button, a
    plain link fallback, a signature and a footer saying why it was sent.

    The logo is a PNG served by the dashboard (public/email/), because mail
    apps do not show inline SVG. Every value put in here is escaped by the
    callers or is our own fixed text."""
    logo = f"{get_settings().dashboard_url.rstrip('/')}/email/safehaven-mark.png"
    href = escape(link, quote=True)
    body = "".join(
        f'<p style="margin:0 0 14px;font-family:{FONT};font-size:16px;line-height:1.6;color:#2E3A3D">{p}</p>'
        for p in paragraphs
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>{heading}</title></head>
<body style="margin:0;padding:0;background:#EEF3F5">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#EEF3F5">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#EEF3F5">
<tr><td align="center" style="padding:32px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px">

<tr><td style="background:#143440;border-radius:18px 18px 0 0;padding:26px 32px">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="vertical-align:middle;padding-right:12px"><img src="{logo}" width="34" height="34" alt="" style="display:block;border:0"></td>
<td style="vertical-align:middle;font-family:{FONT};font-size:16px;font-weight:700;letter-spacing:4px;color:#7CC3DB">SAFEHAVEN AI</td>
</tr></table>
</td></tr>
<tr><td style="background:#7CC3DB;height:4px;line-height:4px;font-size:0">&nbsp;</td></tr>

<tr><td style="background:#FFFFFF;padding:36px 32px 8px">
<h1 style="margin:0 0 18px;font-family:{FONT};font-size:26px;line-height:1.25;font-weight:700;color:#0B0D0E">{heading}</h1>
{body}
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:26px 0 14px"><tr>
<td align="center" bgcolor="#0F6383" style="border-radius:12px">
<a href="{href}" target="_blank" style="display:inline-block;padding:15px 30px;font-family:{FONT};font-size:16px;font-weight:700;color:#FFFFFF;text-decoration:none;border-radius:12px">{button}&nbsp;&rarr;</a>
</td></tr></table>
<p style="margin:0 0 26px;font-family:{FONT};font-size:14px;line-height:1.5;color:#5B676A">{note}</p>
<p style="margin:0 0 6px;font-family:{FONT};font-size:13px;line-height:1.5;color:#5B676A">Button not working? Copy this link into your browser:</p>
<p style="margin:0 0 28px;font-family:{FONT};font-size:13px;line-height:1.5;word-break:break-all"><a href="{href}" style="color:#0F6383">{href}</a></p>
</td></tr>

<tr><td style="background:#FFFFFF;padding:0 32px 32px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #E1E8EC"><tr><td style="padding-top:22px">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="vertical-align:top;padding-right:14px"><img src="{logo}" width="40" height="40" alt="SafeHaven" style="display:block;border:0;border-radius:10px;background:#143440;padding:6px"></td>
<td style="vertical-align:top;font-family:{FONT}">
<div style="font-size:15px;line-height:1.5;color:#2E3A3D">Warm regards,</div>
<div style="font-size:15px;line-height:1.5;font-weight:700;color:#0B0D0E">The SafeHaven team</div>
<div style="font-size:13px;line-height:1.5;color:#0F6383">Calm, watchful care for every bed.</div>
</td></tr></table>
</td></tr></table>
</td></tr>

<tr><td style="background:#F6F9FA;border-radius:0 0 18px 18px;padding:18px 32px;border-top:1px solid #E1E8EC">
<p style="margin:0;font-family:{FONT};font-size:12px;line-height:1.6;color:#6B7679">{reason}<br>
SafeHaven never sends patient information by email, and will never ask for your password.</p>
</td></tr>

</table>
<p style="margin:18px 0 0;font-family:{FONT};font-size:12px;color:#8A9598">SafeHaven AI &middot; {product}</p>
</td></tr></table>
</body></html>"""


def _signature_text() -> str:
    return "\n\nWarm regards,\nThe SafeHaven team\nCalm, watchful care for every bed."


def send_invite_email(to: str, full_name: str, link: str, hours: int) -> EmailResult:
    first = escape(full_name.split()[0]) if full_name.strip() else "there"
    subject = "You're invited to SafeHaven"
    text = (
        f"Hi {full_name.split()[0] if full_name.strip() else 'there'},\n\n"
        "You've been given an account on the SafeHaven ward dashboard: fall and help alerts from the "
        "wrist bands, patients and medication checks, in one place.\n\n"
        f"Choose your password here (the link works once, for {hours} hours):\n{link}"
        + _signature_text()
        + "\n\nYou're receiving this because a SafeHaven administrator added you. Not expecting it? Ignore this email."
    )
    html = _layout(
        preheader="Choose your password to start using the SafeHaven ward dashboard.",
        heading=f"Welcome to SafeHaven, {first}",
        paragraphs=[
            "You've been given an account on the SafeHaven ward dashboard — fall and help alerts from the "
            "wrist bands, your patients and medication checks, all in one place.",
            "Choose your password to get started. A short guided tour will show you around.",
        ],
        button="Set your password",
        link=link,
        note=f"This link works once and expires in {hours} hours.",
        reason="You're receiving this because a SafeHaven administrator added you. Not expecting it? You can ignore this email.",
    )
    return send_email(to, subject, text, html)


def send_reset_email(to: str, full_name: str, link: str, minutes: int) -> EmailResult:
    first = escape(full_name.split()[0]) if full_name.strip() else "there"
    lifetime = f"{minutes // 60} hour{'s' if minutes >= 120 else ''}" if minutes % 60 == 0 else f"{minutes} minutes"
    subject = "Reset your SafeHaven password"
    text = (
        f"Hi {full_name.split()[0] if full_name.strip() else 'there'},\n\n"
        "We received a request to reset your SafeHaven password.\n\n"
        f"Choose a new one here (the link works once, for {lifetime}):\n{link}"
        + _signature_text()
        + "\n\nDidn't ask for this? Ignore this email: your password stays the same."
    )
    html = _layout(
        preheader=f"Choose a new password — this link works for {lifetime}.",
        heading=f"Reset your password, {first}",
        paragraphs=[
            "We received a request to reset your SafeHaven password.",
            "Choose a new one with the button below. Until you do, your current password keeps working.",
        ],
        button="Choose a new password",
        link=link,
        note=f"This link works once and expires in {lifetime}.",
        reason="Didn't ask for this? You can safely ignore this email — your password stays the same.",
    )
    return send_email(to, subject, text, html)


# Patient app emails. Deliberately no name, ward, hospital or medicine: the
# address may be shared with family, and an inbox is not a medical record.
_PATIENT_REASON = (
    "You're receiving this because you agreed, with your care team, to use the SafeHaven patient app. "
    "Not expecting it? You can ignore this email."
)


def send_patient_invite_email(to: str, link: str, hours: int) -> EmailResult:
    subject = "Your care information is ready in SafeHaven"
    text = (
        "Hello,\n\n"
        "Your care team has set up the SafeHaven patient app for you. Sign in to see your medicines, "
        "hospital visits and care instructions, explained in plain words.\n\n"
        f"Sign in here (the link works once, for {hours} hours):\n{link}\n\n"
        'After that, open the app and choose "Email me a sign-in link" whenever you need one.'
        + _signature_text()
        + "\n\n" + _PATIENT_REASON
    )
    html = _layout(
        preheader="Sign in to see your medicines, visits and care instructions.",
        heading="Your care information is ready",
        paragraphs=[
            "Your care team has set up the SafeHaven patient app for you. Sign in to see your medicines, "
            "hospital visits and care instructions, explained in plain words.",
            "There is no password to remember: each time, we email you a link like this one.",
        ],
        button="Sign in to SafeHaven",
        link=link,
        note=f'This link works once and expires in {hours} hours. After that, use "Email me a sign-in link" on the sign-in page.',
        reason=_PATIENT_REASON,
        product="Patient app",
    )
    return send_email(to, subject, text, html)


def send_patient_sign_in_email(to: str, link: str, minutes: int) -> EmailResult:
    subject = "Your SafeHaven sign-in link"
    text = (
        "Hello,\n\n"
        f"Here is your link to sign in to SafeHaven (it works once, for {minutes} minutes):\n{link}"
        + _signature_text()
        + "\n\nDidn't ask for this? Ignore this email — nobody can sign in without the link."
    )
    html = _layout(
        preheader=f"Your sign-in link — it works for {minutes} minutes.",
        heading="Sign in to SafeHaven",
        paragraphs=["Use the button below to sign in to the SafeHaven patient app."],
        button="Sign in",
        link=link,
        note=f"This link works once and expires in {minutes} minutes.",
        reason="Didn't ask for this? You can safely ignore this email — nobody can sign in without the link.",
        product="Patient app",
    )
    return send_email(to, subject, text, html)


def send_caregiver_invite_email(to: str, link: str, hours: int) -> EmailResult:
    # Not even whose care: the inbox may not be private.
    subject = "You've been invited to help with someone's care in SafeHaven"
    reason = (
        "You're receiving this because a hospital care team added you, with the patient's agreement, as someone "
        "who helps with their care. Not expecting it? You can ignore this email."
    )
    text = (
        "Hello,\n\n"
        "A hospital care team has added you to SafeHaven, with the patient's agreement, so you can help with "
        "their care: their medicines and dose times, appointments and care instructions.\n\n"
        f"Sign in here (the link works once, for {hours} hours):\n{link}\n\n"
        'After that, open the app and choose "Email me a sign-in link" whenever you need one.'
        + _signature_text()
        + "\n\n" + reason
    )
    html = _layout(
        preheader="Sign in to help with medicines, appointments and care instructions.",
        heading="You've been invited to help",
        paragraphs=[
            "A hospital care team has added you to SafeHaven, with the patient's agreement, so you can help with "
            "their care: their medicines and dose times, appointments and care instructions.",
            "There is no password to remember: each time, we email you a link like this one.",
        ],
        button="Sign in to SafeHaven",
        link=link,
        note=f'This link works once and expires in {hours} hours. After that, use "Email me a sign-in link" on the sign-in page.',
        reason=reason,
        product="Patient app",
    )
    return send_email(to, subject, text, html)
