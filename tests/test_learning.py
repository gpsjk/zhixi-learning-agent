from datetime import date
import database as db


def make_record(path):
    return db.save_mistake(subject='数学', question='2+3', student_answer='4',
        correct_answer='5', student_thought='', diagnosis={'knowledge_points': ['加法'],
        'error_type': '计算错误'}, practices={'exercises': []}, db_path=path)


def test_review_schedule_and_persistence(tmp_path):
    path = tmp_path / 'learning.db'
    rid = make_record(path)
    assert hasattr(db, 'record_review'), '需要实现持久化复习记录'
    db.record_review(rid, '掌握', '5', today=date(2026, 9, 7), db_path=path)
    row = db.get_mistake(rid, path)
    assert row['status'] == '已掌握'
    assert row['next_review'] == '2026-09-10'
    db.record_review(rid, '忘记', '4', today=date(2026, 9, 10), db_path=path)
    row = db.get_mistake(rid, path)
    assert row['status'] == '待复习'
    assert row['next_review'] == '2026-09-11'
    assert row['review_count'] == 2
    assert len(db.list_reviews(path)) == 2


def test_notes_and_chat_are_isolated_and_deleted(tmp_path):
    path = tmp_path / 'learning.db'
    rid = make_record(path)
    other = make_record(path)
    assert hasattr(db, 'save_chat'), '需要实现按错题保存答疑'
    db.save_chat(rid, '为什么？', '先检查加法。', path)
    db.update_notes(rid, '注意个位计算', True, path)
    assert len(db.list_chat(rid, path)) == 2
    assert db.list_chat(other, path) == []
    assert db.get_mistake(rid, path)['favorite'] == 1
    db.delete_mistake(rid, path)
    assert db.list_chat(rid, path) == []


def test_invalid_review_does_not_write(tmp_path):
    import pytest
    path = tmp_path / 'learning.db'
    rid = make_record(path)
    assert hasattr(db, 'record_review'), '需要实现复习校验'
    with pytest.raises(ValueError):
        db.record_review(rid, '随便', '', db_path=path)
    assert db.list_reviews(path) == []


def test_tutor_demo_is_explicit():
    from llm_service import LLMService
    service = LLMService(api_key='')
    assert hasattr(service, 'answer_followup'), '需要实现上下文答疑'
    result = service.answer_followup({'question': '2+3', 'diagnosis': {}}, [], '为什么？')
    assert '演示' in result
