import json
import pytest
from pydantic import ValidationError
from llm_service import LLMService
from models import Diagnosis, PracticeSet
import database as db

QUESTION = '求极限 题目：已知函数 f(x) = 1 / (x + 1)，求它在区间 [0, 1] 上的定积分。'


def test_integral_never_receives_arithmetic_even_with_generic_diagnosis():
    result = LLMService(api_key='').generate_practices('数学', QUESTION, Diagnosis())
    assert len(result.exercises) == 2
    assert all('定积分' in e.question for e in result.exercises)
    assert all('ln' in e.answer for e in result.exercises)
    assert result.topic == '定积分：一次式倒数的积分'


@pytest.mark.parametrize('question', ['求矩阵的特征值', '计算 sin(x) 的定积分', '求 1/(x+1) 的极限', '解微分方程 y\'=y', '已知f(x)=2+1/(x+1)，求[0,1]上的定积分', '已知f(x)=1/(x+1)，求[-2,0]上的定积分'])
def test_unsupported_topic_does_not_fabricate_similar_exercises(question):
    result = LLMService(api_key='').generate_practices('数学', question, Diagnosis())
    assert result.exercises == []
    assert result.unavailable_reason


def test_incomplete_model_exercises_are_rejected():
    with pytest.raises(ValidationError):
        PracticeSet.model_validate({'exercises': [{'question': '题目'}]})


def test_legacy_demo_practices_repaired_without_changing_question(tmp_path):
    path = tmp_path / 'legacy.db'
    rid = db.save_mistake(subject='数学', question=QUESTION, student_answer='2/3',
        correct_answer='ln2', student_thought='中点值乘区间长度',
        diagnosis={'knowledge_points': ['运算与推理']},
        practices={'exercises': [{'question': '18÷3+4=?'}]}, source_mode='演示数据', db_path=path)
    db.init_db(path)
    row = db.get_mistake(rid, path)
    assert row['question'] == QUESTION
    assert '定积分' in row['practices']['exercises'][0]['question']
    assert row['student_answer'] == '2/3'
    before = json.dumps(row['practices'])
    db.init_db(path)
    assert json.dumps(db.get_mistake(rid, path)['practices']) == before


def test_model_records_not_auto_replaced(tmp_path):
    path = tmp_path / 'model.db'
    original = {'exercises': [{'question': '已审核的练习'}]}
    rid = db.save_mistake(subject='数学', question=QUESTION, student_answer='2/3',
        correct_answer='ln2', student_thought='', diagnosis={}, practices=original,
        source_mode='模型生成', db_path=path)
    assert db.get_mistake(rid, path)['practices'] == original


def test_integral_template_expected_exact_answers():
    result = LLMService(api_key='').generate_practices('数学', QUESTION, Diagnosis())
    assert result.exercises[0].answer == '$\\ln(3/2)$'
    assert result.exercises[1].answer == '$\\ln(4/2)$'
    assert any('近似' in step for step in result.exercises[0].solution_steps)


def test_history_regeneration_ui(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    path = tmp_path / 'ui.db'
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(path))
    monkeypatch.setenv('OPENAI_API_KEY', '')
    rid = db.save_mistake(subject='数学', question=QUESTION, student_answer='2/3',
        correct_answer='ln2', student_thought='', diagnosis={}, practices={},
        source_mode='历史数据', db_path=path)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
    app.sidebar.radio[0].set_value('错题本').run()
    app.button(key=f'regenerate_{rid}').click().run()
    assert not app.exception
    assert db.get_mistake(rid, path)['practices']['topic'] == '定积分：一次式倒数的积分'
