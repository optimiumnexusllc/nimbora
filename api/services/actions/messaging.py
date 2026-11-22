"""The ``send_message`` tool: SMS, WhatsApp or e-mail during the call.

Typical uses: send the address and opening hours, a booking confirmation, a
payment link, a tracking number. Safeguards:

* SMS/WhatsApp go to the caller's own number unless the tool allows another
  number given by the caller;
* a per-call limit (default 3) stops loops;
* every attempt is logged (Activité → Messages), with the provider's id.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any

import httpx
from loguru import logger

from api.services.actions.common import (
    ActionContext,
    ActionError,
    basic_auth_pair,
    check_outbound_url,
    load_credential,
    render_template,
)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
MAX_SMS_CHARS = 1000
TIMEOUT = httpx.Timeout(15.0)


def missing_settings(config: dict[str, Any]) -> list[str]:
    """What still has to be configured before this tool can send."""
    provider = config.get("provider") or "twilio"
    missing = []
    if not (config.get("sender") or "").strip():
        missing.append("sender")
    if provider in {"twilio", "smtp"} and not config.get("credential_uuid"):
        missing.append("credential")
    if provider == "smtp" and not config.get("smtp_host"):
        missing.append("smtp_host")
    if provider == "http" and not config.get("gateway_url"):
        missing.append("gateway_url")
    return missing


def compose_body(
    config: dict[str, Any], args: dict[str, Any], ctx: ActionContext
) -> str:
    template = (config.get("template") or "").strip()
    details = str(args.get("message") or args.get("details") or "").strip()
    if template:
        body = render_template(template, {**ctx.variables(), "details": details})
    else:
        body = details
    if not body:
        raise ActionError("The message is empty: give its content in 'message'")
    limit = 20000 if config.get("channel") == "email" else MAX_SMS_CHARS
    return body[:limit]


def resolve_recipient(
    config: dict[str, Any], args: dict[str, Any], ctx: ActionContext
) -> str:
    from api.services.customer_memory.service import normalize_phone

    channel = config.get("channel") or "sms"
    if channel == "email":
        email = str(args.get("email") or args.get("to") or "").strip()
        if not EMAIL_RE.match(email):
            raise ActionError(
                "Ask the caller for a valid e-mail address and spell it back"
            )
        return email
    requested = normalize_phone(args.get("to")) if args.get("to") else None
    caller = ctx.caller_phone
    if requested and requested != caller:
        if not config.get("allow_other_recipient"):
            raise ActionError("Messages can only be sent to the caller's own number")
        return requested
    if not caller:
        raise ActionError("The caller's number is unknown: ask for a mobile number")
    return caller


async def send_twilio(config, credential, recipient: str, body: str) -> str | None:
    account_sid, auth_token = basic_auth_pair(*credential)
    sender = config["sender"]
    if config.get("channel") == "whatsapp":
        sender = sender if sender.startswith("whatsapp:") else f"whatsapp:{sender}"
        recipient = f"whatsapp:{recipient}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
            data={"From": sender, "To": recipient, "Body": body},
            auth=(account_sid, auth_token),
        )
    if response.status_code >= 300:
        detail = ""
        try:
            detail = response.json().get("message", "")
        except ValueError:
            pass
        raise ActionError(
            f"Twilio refused the message ({response.status_code}) {detail}".strip()
        )
    return response.json().get("sid")


async def send_http(
    config, credential_uuid, organization_id, recipient, body
) -> str | None:
    """Generic gateway: POST {to, from, message, channel} with the credential's auth."""
    url = config.get("gateway_url") or ""
    check_outbound_url(url, "gateway_url")
    headers: dict[str, str] = {}
    if credential_uuid:
        from api.db import db_client
        from api.services.workflow.tools.custom_tool import build_auth_header

        credential = await db_client.get_credential_by_uuid(
            credential_uuid, organization_id
        )
        if credential is None:
            raise ActionError(
                "The credential configured for this tool no longer exists"
            )
        headers.update(build_auth_header(credential))
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
        response = await client.post(
            url,
            json={
                "to": recipient,
                "from": config.get("sender"),
                "message": body,
                "channel": config.get("channel"),
            },
            headers=headers,
        )
    if response.status_code >= 300:
        raise ActionError(
            f"The SMS gateway refused the message ({response.status_code})"
        )
    try:
        data = response.json()
    except ValueError:
        return None
    if isinstance(data, dict):
        return str(data.get("id") or data.get("message_id") or "") or None
    return None


def _send_email_sync(config, username, password, recipient, subject, body) -> str:
    message = EmailMessage()
    message["From"] = formataddr((config.get("sender_name") or "", config["sender"]))
    message["To"] = recipient
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=config["sender"].split("@")[-1])
    message.set_content(body)
    host, port = config["smtp_host"], int(config.get("smtp_port") or 587)
    security = config.get("smtp_security") or "starttls"
    context = ssl.create_default_context()
    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
    try:
        if security == "starttls":
            server.starttls(context=context)
        if username:
            server.login(username, password)
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return message["Message-ID"]


async def send_email(config, credential, recipient, subject, body) -> str | None:
    username, password = basic_auth_pair(*credential)
    check_outbound_url(f"https://{config.get('smtp_host')}", "smtp_host")
    try:
        return await asyncio.to_thread(
            _send_email_sync, config, username, password, recipient, subject, body
        )
    except smtplib.SMTPAuthenticationError as exc:
        raise ActionError("The mail server refused the login") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise ActionError(f"The e-mail could not be sent: {exc}") from exc


async def handle_message(
    ctx: ActionContext, config: dict[str, Any], args: dict[str, Any]
):
    from api.db import db_client

    channel = config.get("channel") or "sms"
    provider = config.get("provider") or "twilio"
    missing = missing_settings(config)
    if missing:
        raise ActionError(
            "This messaging tool is not configured yet (" + ", ".join(missing) + "). "
            "Apologize and offer another way to send the information."
        )
    if ctx.workflow_run_id:
        sent = await db_client.count_messages_for_run(
            ctx.organization_id, ctx.workflow_run_id, ctx.tool_uuid
        )
        if sent >= int(config.get("max_per_call") or 3):
            return {
                "status": "limit_reached",
                "message": "The message limit for this call is reached. Do not retry.",
            }
    recipient = resolve_recipient(config, args, ctx)
    body = compose_body(config, args, ctx)
    subject = None
    if channel == "email":
        subject = render_template(
            str(args.get("subject") or config.get("subject") or "Votre demande"),
            ctx.variables(),
        )[:255]

    provider_id = None
    error = None
    try:
        if provider == "twilio":
            credential = await load_credential(
                ctx.organization_id, config.get("credential_uuid")
            )
            provider_id = await send_twilio(config, credential, recipient, body)
        elif provider == "http":
            provider_id = await send_http(
                config,
                config.get("credential_uuid"),
                ctx.organization_id,
                recipient,
                body,
            )
        else:
            credential = await load_credential(
                ctx.organization_id, config.get("credential_uuid")
            )
            provider_id = await send_email(config, credential, recipient, subject, body)
    except ActionError as exc:
        error = str(exc)
    except httpx.HTTPError as exc:
        error = f"The messaging provider could not be reached ({type(exc).__name__})"

    await db_client.create_sent_message(
        organization_id=ctx.organization_id,
        channel=channel,
        provider=provider,
        recipient=recipient,
        subject=subject,
        body=body,
        status="failed" if error else "sent",
        provider_message_id=provider_id,
        error=error,
        tool_uuid=ctx.tool_uuid,
        workflow_run_id=ctx.workflow_run_id,
    )
    if error:
        logger.warning(f"send_message failed: {error}")
        return {"status": "failed", "message": f"The message was not sent. {error}"}
    shown = recipient if channel == "email" else f"…{recipient[-4:]}"
    return {
        "status": "sent",
        "channel": channel,
        "to": shown,
        "message": "Tell the caller the message was sent.",
    }
