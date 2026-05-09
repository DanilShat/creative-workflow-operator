import pytest

from creative_workflow.server.services.worker_auth import AuthError, WorkerAuthService


def test_worker_token_create_validate_and_revoke(db_session, server_settings):
    service = WorkerAuthService(db_session, server_settings)
    created = service.create_token("designer-laptop-01")

    service.validate("designer-laptop-01", created.token)
    assert service.validate_any_active_token(created.token) == "designer-laptop-01"

    service.revoke_token("designer-laptop-01")
    with pytest.raises(AuthError) as exc:
        service.validate("designer-laptop-01", created.token)
    assert exc.value.code == "token_revoked"


def test_untrusted_worker_rejected_when_registration_disabled(db_session, server_settings):
    service = WorkerAuthService(db_session, server_settings)
    created = service.create_token("designer-laptop-01")
    with pytest.raises(AuthError) as exc:
        service.validate("untrusted-worker", created.token)
    assert exc.value.code == "registration_disabled"

