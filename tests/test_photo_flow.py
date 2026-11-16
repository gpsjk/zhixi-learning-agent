"""端到端界面测试：拍照上传 → 回填 → 提交入库，以及教师端回看作业原图。

识别调用由假的 extract_photo_content 替换，因此测试不联网、不消耗额度。
"""
import base64
import io
from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

import database as db
from llm_service import LLMService
from models import Diagnosis, PhotoBatchExtraction, PracticeExercise, PracticeSet

APP = str(Path(__file__).resolve().parents[1] / 'app.py')


def jpeg_bytes(size=(24, 24)):
    """生成一张真实 JPEG，用于验证照片压缩、入库与渲染。"""
    buffer = io.BytesIO()
    Image.new('RGB', size, (200, 180, 120)).save(buffer, format='JPEG')
    return buffer.getvalue()


def _fake_extraction(self, images, subject=''):
    assert images, '应当至少有张照片'
    return PhotoBatchExtraction.model_validate({'items': [{
        'question_no': 1, 'question': '解方程：2x + 3 = 11', 'student_answer': 'x = 7',
        'student_thought': '移项得 2x = 14', 'correct_answer': '', 'subject': '数学',
        'source_images': [1], 'warnings': ['第二行字迹偏淡，请人工确认'],
    }]})


def test_photo_upload_fills_form_and_saves_photo(monkeypatch, tmp_path):
    path = tmp_path / 'photo.db'
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(path))
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setattr(LLMService, 'extract_photo_batch', _fake_extraction)

    app = AppTest.from_file(APP, default_timeout=30).run()
    app.sidebar.radio[0].set_value('错题诊断').run()
    assert not app.exception

    # 上传照片后可以识别
    app.file_uploader(key='photo_upload').set_value(('作业.jpg', jpeg_bytes(), 'image/jpeg')).run()
    assert not app.exception
    app.button(key='photo_extract').click().run()
    assert not app.exception, app.exception
    assert any('第二行字迹偏淡' in item.value for item in app.warning)

    # 回填后表单拿到识别结果，且学科被自动带上
    app.button(key='photo_fill').click().run()
    assert not app.exception, app.exception
    assert app.text_area(key='question').value == '解方程：2x + 3 = 11'
    assert app.text_area(key='student_answer').value == 'x = 7'
    assert app.selectbox(key='subject').value == '数学'

    # 补齐正确答案后提交，原图随记录一起保存
    app.text_area(key='correct_answer').set_value('x = 4')
    app.text_input(key='student_name').set_value('张小明')
    app.button(key='FormSubmitter:diagnosis_form-开始诊断').click().run()
    assert not app.exception, app.exception
    assert any('诊断结果' in header.value for header in app.header)

    record = db.list_mistakes(path)[0]
    assert record['student_name'] == '张小明'
    assert record['photo_count'] == 1
    photos = db.list_photos(record['id'], path)
    assert photos[0]['name'] == '作业.jpg'
    assert photos[0]['extracted']['question'] == '解方程：2x + 3 = 11'
    assert base64.b64decode(photos[0]['image_base64'])[:2] == b'\xff\xd8'


def test_clear_button_discards_recognition(monkeypatch, tmp_path):
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(tmp_path / 'clear.db'))
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setattr(LLMService, 'extract_photo_batch', _fake_extraction)

    app = AppTest.from_file(APP, default_timeout=30).run()
    app.sidebar.radio[0].set_value('错题诊断').run()
    app.file_uploader(key='photo_upload').set_value(('作业.jpg', jpeg_bytes(), 'image/jpeg')).run()
    app.button(key='photo_extract').click().run()
    assert any('已识别' in item.value for item in app.success)
    app.button(key='photo_clear').click().run()
    assert not app.exception
    assert not any('已识别' in item.value for item in app.success)
    assert app.text_area(key='question').value == ''


def _two_questions(self, images, subject=''):
    return PhotoBatchExtraction.model_validate({'items': [
        {'question': '题目A', 'student_answer': '答A', 'correct_answer': '正A',
         'student_thought': '思A', 'subject': '数学', 'source_images': [1]},
        {'question': '题目B', 'student_answer': '答B', 'correct_answer': '正B',
         'student_thought': '思B', 'subject': '数学', 'source_images': [1],
         'confidence_note': '末行需要核对'},
    ], 'confidence_note': '共拆分两题'})


def _practice_set():
    return PracticeSet(exercises=[
        PracticeExercise(difficulty='基础题', question='练习1', answer='1', solution_steps=['步骤']),
        PracticeExercise(difficulty='变式题', question='练习2', answer='2', solution_steps=['步骤']),
    ])


def test_batch_cards_allow_exclusion_and_save_only_selected(monkeypatch, tmp_path):
    path = tmp_path / 'batch_ui.db'
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(path))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(LLMService, 'extract_photo_batch', _two_questions)

    app = AppTest.from_file(APP, default_timeout=30).run()
    app.sidebar.radio[0].set_value('错题诊断').run()
    app.file_uploader(key='photo_upload').set_value(('双题.jpg', jpeg_bytes(), 'image/jpeg')).run()
    app.button(key='photo_extract').click().run()
    batch_id = app.session_state['photo_result']['batch_id']

    assert app.text_area(key=f'photo_question_{batch_id}_1').value == '题目A'
    assert app.text_area(key=f'photo_question_{batch_id}_2').value == '题目B'
    app.checkbox(key=f'photo_include_{batch_id}_2').uncheck().run()
    app.button(key='photo_batch_submit').click().run()

    assert not app.exception, app.exception
    records = db.list_mistakes(path)
    assert len(records) == 1
    assert records[0]['question'] == '题目A'
    assert records[0]['batch_id'] == batch_id and records[0]['question_no'] == 1
    assert any('成功 1 题' in item.value for item in app.success)


def test_batch_partial_failure_retries_only_failed_question(monkeypatch, tmp_path):
    path = tmp_path / 'retry.db'
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(path))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(LLMService, 'extract_photo_batch', _two_questions)
    allow_second = {'value': False}

    def diagnose(self, subject, question, student_answer, correct_answer, student_thought=''):
        if question == '题目B' and not allow_second['value']:
            from llm_service import LLMServiceError
            raise LLMServiceError('第二题模型暂时失败')
        return Diagnosis(is_correct=False, knowledge_points=['测试知识点'], error_type='计算错误')

    monkeypatch.setattr(LLMService, 'diagnose', diagnose)
    monkeypatch.setattr(LLMService, 'generate_practices', lambda *args, **kwargs: _practice_set())

    app = AppTest.from_file(APP, default_timeout=30).run()
    app.sidebar.radio[0].set_value('错题诊断').run()
    app.file_uploader(key='photo_upload').set_value(('双题.jpg', jpeg_bytes(), 'image/jpeg')).run()
    app.button(key='photo_extract').click().run()
    batch_id = app.session_state['photo_result']['batch_id']
    app.button(key='photo_batch_submit').click().run()

    assert len(db.list_mistakes(path)) == 1
    assert any('第 2 题' in item.value and '暂时失败' in item.value for item in app.error)
    allow_second['value'] = True
    app.button(key='photo_batch_submit').click().run()

    records = db.list_mistakes(path)
    assert len(records) == 2
    assert {(r['batch_id'], r['question_no']) for r in records} == {(batch_id, 1), (batch_id, 2)}
    assert any('成功 2 题' in item.value for item in app.success)


def test_teacher_page_renders_uploaded_photo(monkeypatch, tmp_path):
    path = tmp_path / 'teacher_photo.db'
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(path))
    monkeypatch.setenv('OPENAI_API_KEY', '')
    db.save_mistake(subject='数学', question='解方程 2x+3=11', student_answer='x=7',
                    correct_answer='x=4', student_thought='',
                    diagnosis={'knowledge_points': ['一元一次方程'], 'error_type': '计算错误'},
                    practices={'exercises': []}, student_name='张小明',
                    photos=[{'name': '作业.jpg', 'mime': 'image/jpeg',
                             'image_base64': base64.b64encode(jpeg_bytes()).decode('ascii')}],
                    db_path=path)

    app = AppTest.from_file(APP, default_timeout=30).run()
    app.sidebar.radio[0].set_value('教师端').run()
    assert not app.exception, app.exception
    assert any('知识点错题排行' in header.value for header in app.subheader)
    assert '1' in [metric.value for metric in app.metric]


def test_teacher_page_survives_corrupt_photo(monkeypatch, tmp_path):
    """单张坏图不能让整页统计崩掉。"""
    path = tmp_path / 'corrupt.db'
    monkeypatch.setenv('LEARNING_AGENT_DB_PATH', str(path))
    monkeypatch.setenv('OPENAI_API_KEY', '')
    db.save_mistake(subject='数学', question='坏图题', student_answer='1', correct_answer='2',
                    student_thought='', diagnosis={'knowledge_points': ['加法']}, practices={},
                    student_name='张小明',
                    photos=[{'name': 'bad.jpg', 'mime': 'image/jpeg',
                             'image_base64': base64.b64encode(b'not-an-image').decode('ascii')}],
                    db_path=path)

    app = AppTest.from_file(APP, default_timeout=30).run()
    app.sidebar.radio[0].set_value('教师端').run()
    assert not app.exception, app.exception
    assert any('知识点错题排行' in header.value for header in app.subheader)
