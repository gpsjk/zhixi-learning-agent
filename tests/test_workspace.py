from pathlib import Path
import sqlite3
from streamlit.testing.v1 import AppTest
from database import get_mistake, list_chat, init_db

APP = str(Path(__file__).resolve().parents[1] / 'app.py')


def test_learning_flow(tmp_path, monkeypatch):
    path = tmp_path / 'flow.db'
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(path))
    monkeypatch.setenv('OPENAI_API_KEY', '')
    at = AppTest.from_file(APP, default_timeout=20).run()
    assert not at.exception
    assert at.metric[0].value == '0'
    at.sidebar.radio[0].set_value('错题诊断').run()
    next(b for b in at.button if b.label == '填入数学示例').click().run()
    at.button(key='FormSubmitter:diagnosis_form-开始诊断').click().run()
    assert not at.exception
    assert get_mistake(1, path)['source_mode'] == '演示数据'
    at.sidebar.radio[0].set_value('错题本').run()
    at.text_area(key='notes_text_1').set_value('移项必须变号')
    at.button(key='FormSubmitter:notes_1-保存笔记与收藏').click().run()
    assert get_mistake(1, path)['notes'] == '移项必须变号'
    at.sidebar.radio[0].set_value('复习训练').run()
    at.text_area(key='review_answer_1').set_value('2x=8，所以x=4')
    at.toggle(key='show_1').set_value(True).run()
    at.segmented_control(key='rating_1').set_value('掌握').run()
    next(b for b in at.button if b.label == '完成本次复习').click().run()
    assert not at.exception
    assert get_mistake(1, path)['status'] == '已掌握'
    at.sidebar.radio[0].set_value('学习看板').run()
    assert [m.value for m in at.metric] == ['1', '0', '1', '1']
    at.sidebar.radio[0].set_value('智能答疑').run()
    at.chat_input[0].set_value('为什么要变号？').run()
    assert not at.exception
    assert len(list_chat(1, path)) == 2
    at.sidebar.radio[0].set_value('使用与设置').run()
    assert not at.exception


def test_old_schema_upgrade_preserves_data(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE mistakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL,
            question TEXT NOT NULL, student_answer TEXT NOT NULL, correct_answer TEXT NOT NULL,
            student_thought TEXT NOT NULL DEFAULT '', knowledge_points TEXT NOT NULL,
            error_type TEXT NOT NULL, diagnosis_json TEXT NOT NULL,
            practices_json TEXT NOT NULL, created_at TEXT NOT NULL)''')
        conn.execute("INSERT INTO mistakes VALUES (1,'数学','原有题目','4','5','','[]','计算错误','{}','{}','2026-07-16')")
    init_db(path)
    init_db(path)
    row = get_mistake(1, path)
    assert row['question'] == '原有题目'
    assert row['status'] == '待复习'
    assert row['source_mode'] == '历史数据'
