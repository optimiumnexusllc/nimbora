"""Local accounts keep the full name given at sign-up."""

import uuid


async def test_sign_up_keeps_the_full_name(db_session):
    """The sign-up form sends the name; it comes back on login and /auth/me."""
    user = await db_session.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com",
        password_hash="x",
        name="  Awa Koné ",
    )
    assert user.name == "Awa Koné"
    again = await db_session.get_user_by_email(user.email)
    assert again.name == "Awa Koné"
    nameless = await db_session.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x", name="   "
    )
    assert nameless.name is None
