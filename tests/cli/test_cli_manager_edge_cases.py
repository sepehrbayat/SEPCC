import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_register_real_session_id_moves_pending_to_active_and_maps():
    from cli.manager import CLISessionManager

    with patch("cli.manager.CLISession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.is_busy = False
        mock_session.stop = AsyncMock(return_value=True)
        mock_session_cls.return_value = mock_session

        manager = CLISessionManager(
            workspace_path="/tmp", api_url="http://x/v1", auth_token="proxy-token"
        )
        session, temp_id, is_new = await manager.get_or_create_session()
        assert session is mock_session
        assert is_new is True
        mock_session_cls.assert_called_once()
        assert mock_session_cls.call_args.kwargs["auth_token"] == "proxy-token"
        assert (
            mock_session_cls.call_args.kwargs["prompt_enhancer_model"]
            == "claude-haiku-4-5-20251001"
        )

        ok = await manager.register_real_session_id(temp_id, "real_1")
        assert ok is True

        # Lookup via temp id should resolve to the real session id.
        s2, sid2, is_new2 = await manager.get_or_create_session(session_id=temp_id)
        assert s2 is mock_session
        assert sid2 == "real_1"
        assert is_new2 is False


@pytest.mark.asyncio
async def test_register_real_session_id_missing_temp_id_returns_false():
    from cli.manager import CLISessionManager

    manager = CLISessionManager(workspace_path="/tmp", api_url="http://x/v1")
    ok = await manager.register_real_session_id("missing", "real_1")
    assert ok is False


@pytest.mark.asyncio
async def test_remove_session_pending_stops_and_returns_true():
    from cli.manager import CLISessionManager

    with patch("cli.manager.CLISession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.is_busy = False
        mock_session.stop = AsyncMock(return_value=True)
        mock_session_cls.return_value = mock_session

        manager = CLISessionManager(workspace_path="/tmp", api_url="http://x/v1")
        _, temp_id, _ = await manager.get_or_create_session()

        removed = await manager.remove_session(temp_id)
        assert removed is True
        mock_session.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_session_active_removes_temp_mapping():
    from cli.manager import CLISessionManager

    with patch("cli.manager.CLISession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.is_busy = False
        mock_session.stop = AsyncMock(return_value=True)
        mock_session_cls.return_value = mock_session

        manager = CLISessionManager(workspace_path="/tmp", api_url="http://x/v1")
        _, temp_id, _ = await manager.get_or_create_session()
        await manager.register_real_session_id(temp_id, "real_1")

        removed = await manager.remove_session("real_1")
        assert removed is True

        # Temp ID should no longer resolve to an active session after removal.
        _, sid2, is_new2 = await manager.get_or_create_session(session_id=temp_id)
        assert sid2.startswith("pending_")
        assert sid2 != temp_id
        assert is_new2 is True


@pytest.mark.asyncio
async def test_get_or_create_session_unknown_id_starts_new_pending_session():
    from cli.manager import CLISessionManager

    with patch("cli.manager.CLISession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.is_busy = False
        mock_session.stop = AsyncMock(return_value=True)
        mock_session_cls.return_value = mock_session

        manager = CLISessionManager(workspace_path="/tmp", api_url="http://x/v1")
        session, sid, is_new = await manager.get_or_create_session(
            session_id="missing-real-session"
        )

    assert session is mock_session
    assert sid.startswith("pending_")
    assert sid != "missing-real-session"
    assert is_new is True


@pytest.mark.asyncio
async def test_register_real_session_id_stops_overwritten_active_session():
    from cli.manager import CLISessionManager

    manager = CLISessionManager(workspace_path="/tmp", api_url="http://x/v1")
    old_session = MagicMock()
    old_session.stop = AsyncMock(return_value=True)
    new_session = MagicMock()
    new_session.stop = AsyncMock(return_value=True)

    manager._sessions["real_1"] = old_session
    manager._real_to_temp["real_1"] = "old_temp"
    manager._temp_to_real["old_temp"] = "real_1"
    manager._pending_sessions["pending_new"] = new_session

    ok = await manager.register_real_session_id("pending_new", "real_1")

    assert ok is True
    old_session.stop.assert_awaited_once()
    assert manager._sessions["real_1"] is new_session
    assert "old_temp" not in manager._temp_to_real
    assert manager._real_to_temp["real_1"] == "pending_new"


@pytest.mark.asyncio
async def test_register_real_session_id_stops_overwritten_session_after_lock_release():
    from cli.manager import CLISessionManager

    manager = CLISessionManager(workspace_path="/tmp", api_url="http://x/v1")
    stop_started = asyncio.Event()
    allow_stop = asyncio.Event()

    async def slow_stop():
        stop_started.set()
        await allow_stop.wait()
        return True

    old_session = MagicMock()
    old_session.stop = AsyncMock(side_effect=slow_stop)
    old_session.is_busy = False
    new_session = MagicMock()
    new_session.stop = AsyncMock(return_value=True)
    new_session.is_busy = False

    manager._sessions["real_1"] = old_session
    manager._real_to_temp["real_1"] = "old_temp"
    manager._temp_to_real["old_temp"] = "real_1"
    manager._pending_sessions["pending_new"] = new_session

    register_task = asyncio.create_task(
        manager.register_real_session_id("pending_new", "real_1")
    )
    await stop_started.wait()

    session, sid, is_new = await asyncio.wait_for(
        manager.get_or_create_session(session_id="real_1"),
        timeout=0.05,
    )

    allow_stop.set()
    assert await register_task is True
    assert session is new_session
    assert sid == "real_1"
    assert is_new is False


@pytest.mark.asyncio
async def test_stop_all_handles_stop_exceptions():
    from cli.manager import CLISessionManager

    manager = CLISessionManager(workspace_path="/tmp", api_url="http://x/v1")

    s1 = MagicMock()
    s1.stop = AsyncMock(side_effect=RuntimeError("boom"))
    s1.is_busy = False

    s2 = MagicMock()
    s2.stop = AsyncMock(return_value=True)
    s2.is_busy = False

    manager._sessions["a"] = s1
    manager._pending_sessions["b"] = s2

    await manager.stop_all()
    s1.stop.assert_awaited_once()
    s2.stop.assert_awaited_once()
    assert manager.get_stats()["active_sessions"] == 0
    assert manager.get_stats()["pending_sessions"] == 0
