"""教师端统计与拍照上传的服务层测试；使用临时数据库，不触碰用户历史数据。"""
import base64
import io
import json

import pytest

import database as db
from llm_service import LLMService, LLMServiceError, to_data_url
from models import PhotoExtraction, TeacherReport


def add(path, subject='数学', student='张小明', points=('一元一次方程',), error_type='计算错误'):
    return db.save_mistake(
        subject=subject, question=f'{subject}题目', student_answer='4', correct_answer='5',
        student_thought='', diagnosis={'knowledge_points': list(points), 'error_type': error_type},
        practices={'exercises': []}, student_name=student, db_path=path)


def test_teacher_stats_ranks_knowledge_points(tmp_path):
    path = tmp_path / 'teacher.db'
    add(path, points=('一元一次方程',), error_type='计算错误')
    add(path, student='李小红', points=('一元一次方程',), error_type='审题错误')
    add(path, student='李小红', points=('分式化简',), error_type='计算错误')
    add(path, subject='物理', student='王强', points=('牛顿第二定律',), error_type='公式使用错误')

    stats = db.teacher_stats(db_path=path)
    assert stats['total'] == 4
    assert stats['student_count'] == 3
    assert stats['top_points'][0]['knowledge_point'] == '一元一次方程'
    assert stats['top_points'][0]['count'] == 2
    assert stats['top_points'][0]['student_count'] == 2
    assert stats['top_points'][0]['share'] == 0.5
    assert stats['top_error_types'][0] == {'error_type': '计算错误', 'count': 2, 'share': 0.5}

    filtered = db.teacher_stats(subject='物理', db_path=path)
    assert filtered['total'] == 1
    assert filtered['top_points'][0]['knowledge_point'] == '牛顿第二定律'

    by_student = db.teacher_stats(student='李小红', db_path=path)
    assert by_student['total'] == 2
    assert by_student['by_student'] == [{'student': '李小红', 'count': 2}]


def test_teacher_stats_respects_date_range(tmp_path):
    path = tmp_path / 'range.db'
    add(path, student='张小明')
    stats = db.teacher_stats(start='2000-01-01', end='2000-01-02', db_path=path)
    assert stats['total'] == 0
    assert stats['top_points'] == []


def test_student_names_are_listed_and_blank_ignored(tmp_path):
    path = tmp_path / 'names.db'
    add(path, student='张小明')
    add(path, student='')
    assert db.list_students(path) == ['张小明']
    assert db.get_mistake(1, path)['student_name'] == '张小明'


def test_photos_are_saved_stored_and_deleted(tmp_path):
    path = tmp_path / 'photos.db'
    rid = db.save_mistake(
        subject='数学', question='照片题', student_answer='4', correct_answer='5', student_thought='',
        diagnosis={'knowledge_points': ['加法'], 'error_type': '计算错误'},
        practices={'exercises': []}, student_name='张小明',
        photos=[{'name': 'a.jpg', 'mime': 'image/jpeg', 'image_base64': 'QUJD',
                 'extracted': {'question': '照片题'}}],
        db_path=path)
    record = db.get_mistake(rid, path)
    assert record['photo_count'] == 1
    photos = db.list_photos(rid, path)
    assert len(photos) == 1
    assert photos[0]['name'] == 'a.jpg'
    assert photos[0]['extracted']['question'] == '照片题'
    db.delete_mistake(rid, path)
    assert db.list_photos(rid, path) == []


def test_legacy_database_gains_teacher_columns(tmp_path):
    import sqlite3
    path = tmp_path / 'legacy_teacher.db'
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE mistakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL,
            question TEXT NOT NULL, student_answer TEXT NOT NULL, correct_answer TEXT NOT NULL,
            student_thought TEXT NOT NULL DEFAULT '', knowledge_points TEXT NOT NULL,
            error_type TEXT NOT NULL, diagnosis_json TEXT NOT NULL,
            practices_json TEXT NOT NULL, created_at TEXT NOT NULL)''')
        conn.execute("INSERT INTO mistakes VALUES (1,'数学','旧题','4','5','','[]','计算错误','{}','{}','2020-01-01')")
    db.init_db(path)
    row = db.get_mistake(1, path)
    assert row['student_name'] == ''
    assert row['photo_count'] == 0
    assert db.teacher_stats(db_path=path)['total'] == 1


class _Choice:
    def __init__(self, content):
        self.message = type('Message', (), {'content': content})()


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.content)


class _FakeClient:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)
        self.chat = type('Chat', (), {'completions': self.completions})()


def make_image_bytes():
    return io.BytesIO(b'\xff\xd8\xff\xe0fake-jpeg-bytes')


def test_photo_extraction_sends_images_to_vision_model():
    payload = {'question': '解方程 2x+3=11', 'student_answer': 'x=7', 'student_thought': '移项',
               'subject': '数学', 'warnings': ['第二行字迹不清']}
    client = _FakeClient(json.dumps(payload, ensure_ascii=False))
    service = LLMService(api_key='test-key', model='text-model', vision_model='vision-model', client=client)

    result = service.extract_photo_content([make_image_bytes()], '数学')

    assert isinstance(result, PhotoExtraction)
    assert result.question == '解方程 2x+3=11'
    assert result.warnings == ['第二行字迹不清']
    call = client.completions.calls[0]
    assert call['model'] == 'vision-model'
    content = call['messages'][1]['content']
    assert content[0]['type'] == 'image_url'
    assert content[0]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert content[-1]['type'] == 'text'


def test_vision_model_falls_back_to_main_model_and_mock_mode_is_explicit():
    client = _FakeClient(json.dumps({'question': '题', 'subject': '数学'}, ensure_ascii=False))
    service = LLMService(api_key='test-key', model='main-model', vision_model='', client=client)
    service.extract_photo_content([make_image_bytes()])
    assert client.completions.calls[0]['model'] == 'main-model'

    demo = LLMService(api_key='')
    assert demo.vision_ready is False
    with pytest.raises(LLMServiceError, match='多模态模型'):
        demo.extract_photo_content([make_image_bytes()])


def test_photo_extraction_requires_images_and_unknown_subject_falls_back():
    result = PhotoExtraction.model_validate({'question': '题', 'subject': '天文学', 'warnings': None})
    assert result.subject == '其他'
    assert result.student_answer == ''
    assert result.warnings == []
    service = LLMService(api_key='test-key', model='m')
    with pytest.raises(LLMServiceError, match='请先拍照'):
        service.extract_photo_content([], '数学')


def test_to_data_url_rejects_pdf_and_empty_content():
    with pytest.raises(LLMServiceError, match='PDF'):
        to_data_url(io.BytesIO(b'%PDF-1.4 something'))
    with pytest.raises(LLMServiceError, match='为空'):
        to_data_url(io.BytesIO(b''))


def test_teacher_report_demo_uses_statistics_only():
    demo = LLMService(api_key='')
    report = demo.build_teacher_report({
        'total': 6, 'subject': '数学', 'student': '全部学生',
        'top_points': [{'knowledge_point': '一元一次方程', 'count': 4}],
        'top_error_types': [{'error_type': '计算错误', 'count': 3}],
    })
    assert isinstance(report, TeacherReport)
    assert report.focus_points == ['一元一次方程']
    assert '演示模式' in report.summary
    assert report.lesson_plan and report.exercises


def test_teacher_report_model_path_validates_json():
    payload = {'summary': '计算类问题集中', 'focus_points': ['一元一次方程'],
               'lesson_plan': ['导入', '讲评'], 'advice': ['安排复测'],
               'exercises': [{'knowledge_point': '一元一次方程', 'question': '解 2x+3=11',
                              'answer': 'x=4', 'solution_steps': ['移项', '除以 2']}]}
    client = _FakeClient(json.dumps(payload, ensure_ascii=False))
    service = LLMService(api_key='test-key', model='main-model', client=client)
    report = service.build_teacher_report({'total': 3, 'top_points': []})
    assert report.summary == '计算类问题集中'
    assert report.exercises[0].answer == 'x=4'


def test_photo_base64_round_trip_matches_upload(tmp_path):
    """保存到数据库的照片必须能还原为可显示的图片字节。"""
    path = tmp_path / 'roundtrip.db'
    raw = b'\xff\xd8\xff\xe0real-image-payload'
    rid = db.save_mistake(
        subject='数学', question='题', student_answer='1', correct_answer='2', student_thought='',
        diagnosis={}, practices={},
        photos=[{'name': 'p.jpg', 'mime': 'image/jpeg',
                 'image_base64': base64.b64encode(raw).decode('ascii')}], db_path=path)
    stored = db.list_photos(rid, path)[0]
    assert base64.b64decode(stored['image_base64']) == raw


def test_teacher_page_renders_statistics(monkeypatch, tmp_path):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    path = tmp_path / 'ui.db'
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(path))
    monkeypatch.setenv('OPENAI_API_KEY', '')
    add(path, points=('一元一次方程',))
    add(path, student='李小红', points=('分式化简',))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
    app.sidebar.radio[0].set_value('教师端').run()
    assert not app.exception
    assert any('教师端' in title.value for title in app.title)
    assert any(subheader.value == '错误最集中的知识点' for subheader in app.subheader)
    assert any(subheader.value == '知识点错题排行' for subheader in app.subheader)
    assert '2' in [metric.value for metric in app.metric]


def test_teacher_page_reports_empty_state(monkeypatch, tmp_path):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(tmp_path / 'empty.db'))
    monkeypatch.setenv('OPENAI_API_KEY', '')
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
    app.sidebar.radio[0].set_value('教师端').run()
    assert not app.exception
    assert any('还没有任何错题记录' in info.value for info in app.info)


def test_diagnosis_page_has_photo_upload_controls(monkeypatch, tmp_path):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(tmp_path / 'photo_ui.db'))
    monkeypatch.setenv('OPENAI_API_KEY', '')
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
    app.sidebar.radio[0].set_value('错题诊断').run()
    assert not app.exception
    assert app.file_uploader(key='photo_upload')
    assert app.button(key='photo_extract')
    assert '拍照' in app.expander[0].label
    assert any('最多 5 张' in caption.value for caption in app.caption)

