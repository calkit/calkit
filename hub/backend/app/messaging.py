"""Functionality for working with email."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import emails  # type: ignore
from app.config import settings
from jinja2 import Template


@dataclass
class EmailData:
    html_content: str
    subject: str


def render_email_template(
    *, template_name: str, context: dict[str, Any]
) -> str:
    template_str = (
        Path(__file__).parent / "email-templates" / "build" / template_name
    ).read_text()
    # autoescape so user-controlled context values (e.g. a release note or
    # name) can't inject HTML into outbound emails. Keep this on: it is also
    # what makes values rendered as visible text (e.g. the password in
    # new_account.html) display and copy correctly when they contain HTML
    # characters like '<' -- without escaping, '<' would be parsed as a tag and
    # the value would be corrupted on screen. Rendered HTML still copies the
    # decoded value, so escaping does not change what the recipient pastes.
    html_content = Template(template_str, autoescape=True).render(context)
    return html_content


def send_email(
    *,
    email_to: str,
    subject: str = "",
    html_content: str = "",
) -> None:
    assert settings.emails_enabled, (
        "no provided configuration for email variables"
    )
    message = emails.Message(
        subject=subject,
        html=html_content,
        mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
    )
    smtp_options = {"host": settings.SMTP_HOST, "port": settings.SMTP_PORT}
    if settings.SMTP_TLS:
        smtp_options["tls"] = True
    elif settings.SMTP_SSL:
        smtp_options["ssl"] = True
    if settings.SMTP_USER:
        smtp_options["user"] = settings.SMTP_USER
    if settings.SMTP_PASSWORD:
        smtp_options["password"] = settings.SMTP_PASSWORD
    response = message.send(to=email_to, smtp=smtp_options)
    logging.info(f"send email result: {response}")


def generate_test_email(email_to: str) -> EmailData:
    project_name = settings.PROJECT_NAME
    subject = f"{project_name} - Test email"
    html_content = render_email_template(
        template_name="test_email.html",
        context={"project_name": settings.PROJECT_NAME, "email": email_to},
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_reset_password_email(
    email_to: str, email: str, token: str
) -> EmailData:
    project_name = settings.PROJECT_NAME
    subject = f"{project_name} - Password recovery for user {email}"
    link = f"{settings.server_host}/reset-password?token={token}"
    html_content = render_email_template(
        template_name="reset_password.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "username": email,
            "email": email_to,
            "valid_hours": settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS,
            "link": link,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_release_share_email(
    email_to: str,
    project_name: str,
    release_name: str,
    link: str,
    inviter: str,
    permission: str,
    note: str | None = None,
) -> EmailData:
    subject = f"{inviter} shared {project_name} ({release_name}) with you"
    action = "view and comment on" if permission == "comment" else "view"
    html_content = render_email_template(
        template_name="release_share.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "shared_project": project_name,
            "release_name": release_name,
            "inviter": inviter,
            "action": action,
            "note": note,
            "link": link,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_project_invitation_email(
    email_to: str,
    project_name: str,
    link: str,
    inviter: str,
    role: str,
) -> EmailData:
    subject = f"{inviter} invited you to collaborate on {project_name}"
    html_content = render_email_template(
        template_name="project_invitation.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "shared_project": project_name,
            "inviter": inviter,
            "role": role,
            "link": link,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_new_account_email(
    email_to: str, username: str, password: str
) -> EmailData:
    project_name = settings.PROJECT_NAME
    subject = f"{project_name} - New account for user {username}"
    html_content = render_email_template(
        template_name="new_account.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "username": username,
            "password": password,
            "email": email_to,
            "link": settings.server_host,
        },
    )
    return EmailData(html_content=html_content, subject=subject)
