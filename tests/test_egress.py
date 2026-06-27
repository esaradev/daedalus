"""Egress: default-deny allowlist + NemoClaw policy emission."""

from daedalus.egress import Egress, DEFAULT_ALLOW


def test_defaults_allow_stripe_and_openrouter():
    e = Egress()
    assert e.check("api.stripe.com", 443)[0] is True
    assert e.check("openrouter.ai", 443)[0] is True


def test_unlisted_host_denied():
    e = Egress()
    ok, reason = e.check("evil.example.com", 443)
    assert ok is False
    assert "not on the allowlist" in reason


def test_wrong_port_denied():
    e = Egress(allowed={("api.stripe.com", 443)})
    assert e.check("api.stripe.com", 80)[0] is False


def test_allow_adds_endpoint():
    e = Egress(allowed=set())
    assert e.check("openrouter.ai")[0] is False
    e.allow("openrouter.ai")
    assert e.check("openrouter.ai")[0] is True


def test_policy_yaml_shape():
    e = Egress(allowed={("api.stripe.com", 443)})
    y = e.policy_yaml()
    assert "preset:" in y and "name: daedalus" in y
    assert "host: api.stripe.com" in y and "port: 443" in y
    assert "default-deny" in y.lower()


def test_default_allow_constant_nonempty():
    assert ("api.stripe.com", 443) in DEFAULT_ALLOW
