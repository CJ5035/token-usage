"""测试设施回归锚: 默认不触碰真实机器采集源 (20260917).

背景: 读取端点 (/api/dashboard?scope=all, /api/report/*) 会触发 WorkBuddy
本地导入后台线程, 其扫描根默认是真实机器的 ~/.workbuddy/projects, 会把真实
用量行写进用例的临时库 —— 仅按子集执行时暴露, 全量运行被掩盖
(见 doc/20260917-WorkBuddy本地导入测试隔离缺陷修复实施计划.md)。

本文件断言 conftest 的 isolate_workbuddy_scan_root 夹具确实生效, 防止
将来有人误删该夹具、或把扫描根改回真实目录。
"""
from app import workbuddy_local_api


def test_wb_scan_root_isolated_to_tmp():
    """默认扫描根指向临时空目录, 且扫描结果为空 (不含本机真实会话)."""
    root = str(workbuddy_local_api.WORKBUDDY_PROJECTS)
    assert "_empty_wb_projects" in root, f"WorkBuddy 扫描根未隔离: {root}"
    assert workbuddy_local_api.scan_session_files() == []


def test_wb_own_fixture_still_overrides_isolation(tmp_path, monkeypatch):
    """显式把扫描根指向自建目录时, 夹具不得覆盖 (monkeypatch 后置优先生效)."""
    projects = tmp_path / "custom" / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setattr(workbuddy_local_api, "WORKBUDDY_PROJECTS", projects)
    assert str(workbuddy_local_api.WORKBUDDY_PROJECTS) == str(projects)
