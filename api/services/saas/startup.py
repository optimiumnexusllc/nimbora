"""Startup checks for SaaS operator mode."""

from loguru import logger

from api import constants


class InsecureSaasConfiguration(RuntimeError):
    pass


INSECURE_JWT_SECRETS = {"", "change-me-in-production", "changeme", "secret"}


def validate_saas_configuration() -> list[str]:
    """Problems that make a multi-tenant deployment unsafe to start."""
    problems: list[str] = []
    if not constants.SAAS_MODE:
        return problems
    if constants.DEPLOYMENT_MODE != "oss":
        problems.append("SAAS_MODE requires DEPLOYMENT_MODE=oss (self-hosted)")
    if constants.AUTH_PROVIDER != "local":
        problems.append("SAAS_MODE requires AUTH_PROVIDER=local")
    secret = constants.OSS_JWT_SECRET or ""
    if secret in INSECURE_JWT_SECRETS or len(secret) < 32:
        problems.append(
            "OSS_JWT_SECRET must be a random value of at least 32 characters "
            "(e.g. `openssl rand -hex 32`)"
        )
    if constants.STRIPE_SECRET_KEY and not constants.STRIPE_WEBHOOK_SECRET:
        problems.append(
            "STRIPE_WEBHOOK_SECRET is required when STRIPE_SECRET_KEY is set"
        )
    if constants.CONTACT_CENTER_ENABLED and not constants.ASTERISK_ARI_PASSWORD:
        problems.append("ASTERISK_ARI_PASSWORD is required with CONTACT_CENTER_ENABLED")
    return problems


async def run_saas_startup_checks() -> None:
    if not constants.SAAS_MODE:
        return
    problems = validate_saas_configuration()
    if problems:
        for problem in problems:
            logger.error("Unsafe SaaS configuration: {}", problem)
        raise InsecureSaasConfiguration("; ".join(problems))
    from api.services.saas.subscription_service import ensure_default_plans

    await ensure_default_plans()
    logger.info("SaaS operator mode enabled ({})", constants.SAAS_PLATFORM_NAME)

    if constants.CONTACT_CENTER_ENABLED:
        # Make sure Asterisk's generated includes exist and match the DB after
        # a restart or a fresh volume. Best effort: Asterisk may still boot.
        from api.services.contact_center.asterisk_config import (
            regenerate_asterisk_config,
        )

        try:
            await regenerate_asterisk_config()
        except Exception:
            logger.opt(exception=True).warning(
                "Could not render contact-center configuration at startup"
            )
