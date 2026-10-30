"""OpenCode adapter: batch-5.1 upstream SQLite-v2 JSON fixture (FIXTURE) + batch-4 constructed DB."""
from . import native_batch4, native_batch5_1


def default_root():
    return native_batch5_1._workspace_root()


def list_sessions(root=None):
    rows = native_batch5_1.list_opencode_sessions()
    if rows:
        return rows
    return native_batch4.list_sessions("opencode", root=root)


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    if path and path.endswith("ses_fixture_v2.json"):
        return native_batch5_1.load_opencode_fixture(path)
    if path and (path.endswith(".db") or path.endswith(".sqlite")):
        return native_batch4.load_session("opencode", root=root, session=session,
                                          path=path, keep_system=keep_system)
    paths = native_batch5_1.fixture_paths("opencode")
    if not path and paths:
        return native_batch5_1.load_opencode_fixture(paths[0])
    return native_batch4.load_session("opencode", root=root, session=session,
                                      path=path, keep_system=keep_system)
