import os

import pytest

from tests.helpers import make_trace
from tracefi.reports import decision_text, export_html, postmortem
from tracefi.security.files import write_export


def test_reports_redact_raw_trace_and_escape_control_characters():
    trace = make_trace()
    trace["context"]["private_key"] = "SECRET_SENTINEL"
    trace["agent"]["name"] = "\x1b[2Jmalicious"
    trace["proposal"]["protocol"] = "<script>alert(1)</script>"
    trace["retrieval"] = {"required_features": 42}
    for report in (postmortem(trace), export_html(trace)):
        assert "SECRET_SENTINEL" not in report
        assert "\x1b" not in report
    exported = export_html(trace)
    assert "<script>alert(1)</script>" not in exported
    assert "&lt;script&gt;" in exported
    assert "Invalid observation" in postmortem(trace)
    assert "\x1b" not in decision_text({"action": "\x1b[2J"})


def test_export_is_private_atomic_and_non_overwriting(tmp_path):
    target = tmp_path / "report.html"
    write_export(target, "complete")
    assert target.read_text() == "complete"
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_export(target, "replacement")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        write_export(link, "leak")
    assert target.read_text() == "complete"
    assert not list(tmp_path.glob(".tracefi-*"))


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs POSIX permissions")
def test_export_failures_preserve_the_error_and_leave_no_temporary_files(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        with pytest.raises(PermissionError):
            write_export(locked / "output", "data")
    finally:
        locked.chmod(0o700)
    with pytest.raises(UnicodeEncodeError):
        write_export(tmp_path / "invalid", "\ud800")
    assert list(tmp_path.iterdir()) == [locked]
    assert list(locked.iterdir()) == []


def test_export_publication_stays_on_destination_filesystem(tmp_path, monkeypatch):
    import tracefi.security.files as files

    link = files.os.link

    def same_filesystem(source, destination):
        assert os.path.dirname(source) == str(destination.parent)
        link(source, destination)

    monkeypatch.setattr(files.os, "link", same_filesystem)
    write_export(tmp_path / "report", "data")
    assert (tmp_path / "report").read_text() == "data"
