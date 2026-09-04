"""opencode_api.py 单测: UA 常量合法性."""
from app import opencode_api


def test_user_agent_is_plausible_firefox():
    """与 bai_api 同步修正: 畸形 UA (缺 rv:) 是 bot 评分信号."""
    assert "rv:" in opencode_api.USER_AGENT
    assert "Gecko/20100101 Firefox/" in opencode_api.USER_AGENT
