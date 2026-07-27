# tests/test_http_auth.py

from __future__ import annotations

from types import SimpleNamespace

import aiosqlite
import pytest
import pytest_asyncio

from commamatrix.builtin.http_connector.auth import AuthError, Authorizer


@pytest_asyncio.fixture
async def sqlite_agent(tmp_path):
    db = await aiosqlite.connect(tmp_path / "auth.db")
    db.row_factory = aiosqlite.Row

    class Storage:
        async def execute(self, query: str, params: tuple = ()) -> list[dict]:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            await db.commit()
            return [dict(row) for row in rows]

    yield SimpleNamespace(storage=Storage())
    await db.close()


@pytest.mark.asyncio
async def test_authorizer_admin_login_password_and_single_use_invite(sqlite_agent, capsys):
    auth = Authorizer(sqlite_agent, "test_app", "test-secret-0123456789012345678901", 86400)
    await auth.init_db()

    output = capsys.readouterr().out
    admin_password = output.rsplit(": ", 1)[1].strip()
    token = await auth.login("admin", admin_password)
    admin = await auth.authenticate(token)
    assert admin.is_admin is True

    invite = await auth.create_invite()
    user = await auth.register_with_invite(invite, "alice", "password")
    assert user.username == "alice"
    with pytest.raises(AuthError, match="invitation"):
        await auth.register_with_invite(invite, "bob", "password")

    await auth.change_password(user, "password", "new-password")
    assert await auth.authenticate(await auth.login("alice", "new-password")) == user


@pytest.mark.asyncio
async def test_authorizer_isolates_apps(sqlite_agent, capsys):
    first = Authorizer(sqlite_agent, "first", "test-secret-0123456789012345678901", 86400)
    second = Authorizer(sqlite_agent, "second", "test-secret-0123456789012345678901", 86400)
    await first.init_db()
    capsys.readouterr()
    await second.init_db()
    second_password = capsys.readouterr().out.rsplit(": ", 1)[1].strip()

    with pytest.raises(AuthError, match="Invalid username or password"):
        await first.login("admin", second_password)
    assert (await second.authenticate(await second.login("admin", second_password))).app_name == "second"
