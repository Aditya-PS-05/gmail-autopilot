"""Tests for RoutedLLM (the auto-backend's router)."""

import pytest

from courier.adapters.llm_fake import FakeLLMClient
from courier.adapters.llm_routed import RoutedLLM
from courier.errors import AuthError, PermanentError, TransientError
from courier.models import RelationshipSignal

_USER = "email_id: x\nsubject: a question?"


def test_routed_uses_first_provider_when_healthy():
    a = FakeLLMClient()
    b = FakeLLMClient()
    routed = RoutedLLM({"fast": [("a", a), ("b", b)]})

    result = routed.complete("sys", _USER, RelationshipSignal, "fast")

    assert result.email_id == "x"


def test_routed_falls_through_on_permanent_error():
    a = FakeLLMClient()
    a.fail_on_next_call("RelationshipSignal", PermanentError("a broken"))
    b = FakeLLMClient()
    routed = RoutedLLM({"fast": [("a", a), ("b", b)]})

    result = routed.complete("sys", _USER, RelationshipSignal, "fast")

    assert result.email_id == "x"  # b returned the canned response


def test_routed_falls_through_on_auth_error():
    a = FakeLLMClient()
    a.fail_on_next_call("RelationshipSignal", AuthError("a key revoked"))
    b = FakeLLMClient()
    routed = RoutedLLM({"fast": [("a", a), ("b", b)]})

    result = routed.complete("sys", _USER, RelationshipSignal, "fast")

    assert result.email_id == "x"


def test_routed_falls_through_on_transient_then_succeeds():
    a = FakeLLMClient()
    a.fail_on_next_call("RelationshipSignal", TransientError("a timeout"))
    b = FakeLLMClient()
    routed = RoutedLLM({"fast": [("a", a), ("b", b)]})

    result = routed.complete("sys", _USER, RelationshipSignal, "fast")

    assert result.email_id == "x"


def test_routed_raises_transient_when_all_fail_transient():
    a = FakeLLMClient()
    a.fail_on_next_call("RelationshipSignal", TransientError("a timeout"))
    b = FakeLLMClient()
    b.fail_on_next_call("RelationshipSignal", TransientError("b timeout"))
    routed = RoutedLLM({"fast": [("a", a), ("b", b)]})

    with pytest.raises(TransientError):
        routed.complete("sys", _USER, RelationshipSignal, "fast")


def test_routed_uses_separate_routes_per_hint():
    smart_only = FakeLLMClient()
    smart_only.fail_on_next_call("RelationshipSignal", PermanentError("smart broken"))
    fast_only = FakeLLMClient()
    routed = RoutedLLM(
        {
            "fast": [("fast_p", fast_only)],
            "smart": [("smart_p", smart_only)],
        }
    )

    # Smart route has only the failing provider — should raise.
    with pytest.raises(PermanentError):
        routed.complete("sys", _USER, RelationshipSignal, "smart")

    # Fast route is independent — succeeds.
    result = routed.complete("sys", _USER, RelationshipSignal, "fast")
    assert result.email_id == "x"
