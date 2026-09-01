from app.services.updater import _normalize_url


def test_normalize_url_accepts_equivalent_https_and_ssh():
    https_url = "https://github.com/rozgladacz/opos"
    ssh_url = "git@github.com:rozgladacz/opos.git"
    assert _normalize_url(https_url) == _normalize_url(ssh_url)


def test_normalize_url_trims_trailing_slashes_and_git_suffix():
    assert _normalize_url("https://example.com/team/repo.git/") == "example.com/team/repo"


def test_normalize_url_handles_empty_string():
    assert _normalize_url("   ") == ""
