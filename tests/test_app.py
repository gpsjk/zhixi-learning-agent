import os

from streamlit.testing.v1 import AppTest


def test_app_has_submission_form_and_history_page(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_AGENT_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")

    at = AppTest.from_file(app_path, default_timeout=20).run()
    assert not at.exception
    at.sidebar.radio[0].set_value('错题诊断').run()
    assert at.title[0].value == "课后错题诊断与答疑智能体"
    assert at.button(key="FormSubmitter:diagnosis_form-开始诊断")

    at.sidebar.radio[0].set_value("错题本").run()
    assert not at.exception
    assert any(title.value == "错题本" for title in at.title)


def test_mock_submission_shows_diagnosis_and_practices(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_AGENT_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    at = AppTest.from_file(app_path, default_timeout=20).run()
    at.sidebar.radio[0].set_value('错题诊断').run()

    at.text_area(key="question").set_value("计算 2 + 3")
    at.text_area(key="student_answer").set_value("4")
    at.text_area(key="correct_answer").set_value("5")
    at.button(key="FormSubmitter:diagnosis_form-开始诊断").click().run()

    assert not at.exception
    assert any("诊断结果" in header.value for header in at.header)
    assert any("同类练习" in header.value for header in at.header)


def test_complete_flow_saves_history_and_deletes_record(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_AGENT_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    at = AppTest.from_file(app_path, default_timeout=20).run()
    at.sidebar.radio[0].set_value('错题诊断').run()

    at.text_area(key="question").set_value("计算 18 ÷ 3 + 4")
    at.text_area(key="student_answer").set_value("9")
    at.text_area(key="correct_answer").set_value("10")
    at.text_area(key="student_thought").set_value("先算除法，再算加法")
    at.button(key="FormSubmitter:diagnosis_form-开始诊断").click().run()

    at.sidebar.radio[0].set_value("错题本").run()
    assert any("计算 18 ÷ 3 + 4" in expander.label for expander in at.expander)
    assert any(subheader.value == "第一处错误" for subheader in at.subheader)
    assert any(subheader.value == "完整步骤" for subheader in at.subheader)
    at.checkbox(key='confirm_1').check().run()
    at.button(key="delete_1").click().run()
    assert any("错题本还是空的" in info.value for info in at.info)
