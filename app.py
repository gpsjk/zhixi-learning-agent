import streamlit as st
from uuid import uuid4

from database import find_batch_record, init_db, save_mistake, get_mistake
from llm_service import LLMService, LLMServiceError, to_data_url
from photo_pipeline import included_items, merge_adjacent_items, normalize_photo_batch
import teacher_ui as teacher
import workspace_ui as ui
import design
from models import SUBJECTS
from cloud_secrets import bridge_streamlit_secrets

# 云端部署时把 st.secrets 注入环境变量；本地无 secrets 时静默跳过。
bridge_streamlit_secrets()


PHOTO_LIMIT = 5
PAGES = ["学习看板", "错题诊断", "错题本", "复习训练", "智能答疑", "教师端", "使用与设置"]


def _photos():
    """返回本次上传的照片列表，拍照与相册选择合并，最多 PHOTO_LIMIT 张。"""
    st.markdown('**拍照或选择作业照片**')
    st.caption('支持 JPG / PNG，最多 5 张；可自动拆分多道题并逐题核对。')
    left, right = st.columns(2)
    with left:
        camera = st.camera_input('用摄像头拍照', key='photo_camera')
    with right:
        uploaded = st.file_uploader('或从相册 / 文件选择', type=['jpg', 'jpeg', 'png'],
                                    accept_multiple_files=True, key='photo_upload')
    images = ([camera] if camera is not None else []) + list(uploaded or [])
    if len(images) > PHOTO_LIMIT:
        st.warning(f'一次最多识别 {PHOTO_LIMIT} 张，已按顺序取前 {PHOTO_LIMIT} 张。')
        images = images[:PHOTO_LIMIT]
    for index, image in enumerate(images, start=1):
        st.image(image, caption=f'待识别照片 {index}', width='stretch')
    return images


def _run_extraction(service: LLMService, images, subject: str) -> None:
    try:
        with st.spinner('正在识别照片中的题目与作答……'):
            extraction = service.extract_photo_batch(images, subject)
            photos = [{'name': getattr(image, 'name', '') or f'照片{index}',
                       'mime': getattr(image, 'type', '') or 'image/jpeg',
                       'image_base64': to_data_url(image).split(',', 1)[-1],
                       'extracted': {}}
                      for index, image in enumerate(images, start=1)]
    except LLMServiceError as exc:
        st.session_state.pop('photo_result', None)
        st.error(str(exc))
        st.info('请检查 `.env` 中的 OPENAI_API_KEY 与 OPENAI_VISION_MODEL 配置；'
                '也可以手动填写题目后继续使用其余功能。')
        return
    payload = extraction.model_dump()
    batch = normalize_photo_batch(extraction, len(photos))
    stored_payload = dict(payload)
    if extraction.items:
        stored_payload.update(extraction.items[0].model_dump())
    for photo in photos:
        photo['extracted'] = stored_payload
    st.session_state['photo_result'] = {
        'batch_id': f"photo-{uuid4().hex}",
        'batch': batch,
        'photos': photos,
        'summary': {},
    }
    st.rerun()


def _apply_result() -> None:
    """把已识别的文字回填到诊断表单。

    只在本轮脚本最前面调用：此时表单控件尚未创建，可以安全写入这些键；
    表单随后渲染时会读到新值。
    """
    pending = st.session_state.pop('photo_pending_fill', None)
    if not pending:
        return
    st.session_state['question'] = pending['question']
    st.session_state['student_answer'] = pending['student_answer']
    st.session_state['student_thought'] = pending['student_thought']
    st.session_state['correct_answer'] = pending.get('correct_answer', '')
    if pending['subject'] != '其他':
        st.session_state['subject'] = pending['subject']
    st.session_state['photo_recognized'] = True


def _source_photos(result: dict, item: dict) -> list[dict]:
    photos = result.get('photos') or []
    if item.get('source_unknown') or not item.get('source_images'):
        return photos
    numbers = set(item['source_images'])
    return [photo for index, photo in enumerate(photos, start=1) if index in numbers]


def _process_photo_batch(service: LLMService) -> None:
    result = st.session_state.get('photo_result')
    if not result:
        return
    batch_id = result['batch_id']
    successes = 0
    failures = []
    for item in included_items(result['batch']['items']):
        number = int(item['question_no'])
        existing = find_batch_record(batch_id, number)
        if existing is not None:
            result['batch']['items'][number - 1]['saved_record_id'] = existing['id']
            result['batch']['items'][number - 1]['error'] = ''
            successes += 1
            continue
        missing = [label for label, field in (
            ('题目', 'question'), ('学生答案', 'student_answer'), ('正确答案', 'correct_answer')
        ) if not str(item.get(field, '')).strip()]
        if missing:
            message = f"请补充：{'、'.join(missing)}"
            result['batch']['items'][number - 1]['error'] = message
            failures.append((number, message))
            continue
        try:
            diagnosis = service.diagnose(
                item['subject'], item['question'], item['student_answer'],
                item['correct_answer'], item.get('student_thought', ''),
            )
            practices = service.generate_practices(item['subject'], item['question'], diagnosis)
            record_id = save_mistake(
                subject=item['subject'], question=item['question'],
                student_answer=item['student_answer'], correct_answer=item['correct_answer'],
                student_thought=item.get('student_thought', ''),
                diagnosis=diagnosis.model_dump(), practices=practices.model_dump(),
                source_mode='演示数据' if service.is_mock_mode else '模型生成',
                student_name=st.session_state.get('photo_grade_name', '').strip(),
                photos=_source_photos(result, item), batch_id=batch_id, question_no=number,
            )
            result['batch']['items'][number - 1]['saved_record_id'] = record_id
            result['batch']['items'][number - 1]['error'] = ''
            successes += 1
        except Exception as exc:
            message = str(exc) if isinstance(exc, LLMServiceError) else f"处理失败：{exc}"
            result['batch']['items'][number - 1]['error'] = message
            failures.append((number, message))
    result['summary'] = {'successes': successes, 'failures': failures}
    st.session_state['photo_result'] = result


def _photo_result_panel(service: LLMService) -> None:
    result = st.session_state.get('photo_result')
    if not result:
        return
    batch = result['batch']
    batch_id = result['batch_id']
    active_count = sum(item.get('merged_into') is None for item in batch['items'])
    st.success(f"已识别 {len(result['photos'])} 张照片并拆分出 {active_count} 道题，请逐题核对。")
    if batch.get('confidence_note'):
        st.caption('识别说明：' + batch['confidence_note'])
    for warning in batch.get('warnings') or []:
        st.warning(warning)
    for index, item in enumerate(batch['items']):
        if item.get('merged_into') is not None:
            continue
        number = item['question_no']
        with st.container(border=True):
            st.markdown(f"**第 {number} 题**")
            sources = '、'.join(f'图片 {value}' for value in item.get('source_images') or [])
            if item.get('source_unknown'):
                sources = (sources + '；' if sources else '') + '来源未完全确认'
            st.caption('来源：' + sources)
            if item.get('confidence_note'):
                st.caption('识别限制：' + item['confidence_note'])
            for warning in item.get('warnings') or []:
                st.warning(warning)
            included = st.checkbox('包含此题', value=bool(item.get('included', True)),
                                   key=f'photo_include_{batch_id}_{number}')
            question = st.text_area('题目', value=item.get('question', ''),
                                    key=f'photo_question_{batch_id}_{number}')
            answer_left, answer_right = st.columns(2)
            with answer_left:
                student_answer = st.text_area('学生答案', value=item.get('student_answer', ''),
                                              key=f'photo_answer_{batch_id}_{number}')
            with answer_right:
                correct_answer = st.text_area('正确答案', value=item.get('correct_answer', ''),
                                              key=f'photo_correct_{batch_id}_{number}')
            thought = st.text_area('解题过程或草稿', value=item.get('student_thought', ''),
                                   key=f'photo_thought_{batch_id}_{number}')
            subject = st.selectbox('学科', SUBJECTS,
                                   index=SUBJECTS.index(item['subject']) if item.get('subject') in SUBJECTS else 0,
                                   key=f'photo_subject_{batch_id}_{number}')
            item.update(included=included, question=question, student_answer=student_answer,
                        correct_answer=correct_answer, student_thought=thought, subject=subject)
            if item.get('saved_record_id'):
                st.success(f"已保存为错题 #{item['saved_record_id']}")
            if item.get('error'):
                st.error(item['error'])
            has_next = any(candidate.get('merged_into') is None
                           for candidate in batch['items'][index + 1:])
            if has_next and st.button('与下一题合并', key=f'photo_merge_{batch_id}_{number}'):
                batch['items'] = merge_adjacent_items(batch['items'], index)
                st.session_state['photo_result'] = result
                st.rerun()
    summary = result.get('summary') or {}
    if summary:
        if summary.get('successes'):
            st.success(f"本批次成功 {summary['successes']} 题。")
        for number, message in summary.get('failures') or []:
            st.error(f"第 {number} 题：{message}")
    with st.container(horizontal=True):
        if st.button('诊断并保存选中题目', type='primary', key='photo_batch_submit'):
            _process_photo_batch(service)
            st.rerun()
        first = next((item for item in batch['items'] if item.get('merged_into') is None), None)
        if first and st.button('回填第一题到单题表单', key='photo_fill'):
            st.session_state['photo_pending_fill'] = first
            st.rerun()
        if st.button('清除识别结果', key='photo_clear'):
            st.session_state.pop('photo_result', None)
            st.rerun()


def _reset_form_state() -> None:
    st.session_state.pop('photo_result', None)
    st.session_state.pop('photo_pending_fill', None)
    st.session_state.pop('photo_recognized', None)
    for key in ('question', 'student_answer', 'correct_answer', 'student_thought'):
        st.session_state.pop(key, None)


def render_diagnosis(diagnosis: dict) -> None:
    st.header("诊断结果")
    if diagnosis.get("is_correct"):
        st.success("✅ 回答正确")
    else:
        st.error("❌ 回答有误")

    st.subheader("涉及知识点")
    st.write("、".join(diagnosis.get("knowledge_points") or ["未识别"]))

    left, right = st.columns(2)
    with left:
        st.subheader("做对的部分")
        correct_parts = diagnosis.get("correct_parts") or []
        if correct_parts:
            for item in correct_parts:
                st.markdown(f"- {item}")
        else:
            st.write("暂无可确认的正确步骤。")
        st.subheader("第一处错误")
        st.write(diagnosis.get("first_error", "未定位到明确步骤"))
        st.subheader("错误类型")
        st.write(diagnosis.get("error_type", "基础知识不牢"))
    with right:
        st.subheader("错误原因")
        st.write(diagnosis.get("error_reason", "需要进一步判断"))
        st.subheader("正确解题思路")
        st.write(diagnosis.get("solution_idea", "请按正确方法重新梳理"))
        st.subheader("易错提醒")
        st.warning(diagnosis.get("warning", "完成后请复查关键步骤。"))

    st.subheader("完整步骤")
    for index, step in enumerate(diagnosis.get("solution_steps") or [], start=1):
        st.markdown(f"**{index}.** {step}")


def render_practices(practices: dict) -> None:
    st.header("同类练习")
    if practices.get('unavailable_reason'):
        st.info(practices['unavailable_reason'])
    if practices.get('topic'):
        st.caption('匹配知识点：' + practices['topic'])
    if practices.get('generation_mode') == '本地题型模板':
        st.caption('来自本地题型模板，非 AI 实时生成。仅匹配已支持的具体题型。')
    exercises = practices.get("exercises") or []
    for index, exercise in enumerate(exercises, start=1):
        st.subheader(f"练习 {index} · {exercise.get('difficulty', '练习题')}")
        st.write(exercise.get("question", ""))
        with st.expander(f"查看练习 {index} 的答案与步骤"):
            st.markdown("**答案**")
            st.write(exercise.get("answer", ""))
            st.markdown("**解题步骤**")
            for step_number, step in enumerate(exercise.get("solution_steps") or [], start=1):
                st.markdown(f"{step_number}. {step}")


def render_submission_page(service: LLMService) -> None:
    design.page_header("课后错题诊断与答疑智能体", "完整记录题目与思路，让诊断更有依据。", "DIAGNOSIS / 错题诊断")
    if service.is_mock_mode:
        st.info("演示模式：诊断是模板、练习为固定示例，不代表对本题的真实分析。配置模型后可获得针对性结果。")

    with st.expander('📷 拍照上传作业（自动识别题目与作答）', expanded=False):
        if not service.vision_ready:
            st.warning('拍照识别需要真实的多模态模型，当前不可用。'
                       '请在 `.env` 中同时配置 OPENAI_API_KEY 与 OPENAI_VISION_MODEL。')
        images = _photos()
        name_column, subject_column = st.columns([1, 2])
        with name_column:
            photo_student = st.text_input('学生姓名（用于教师端统计）', key='photo_grade_name',
                                          max_chars=30, placeholder='例如：张小明')
            st.caption('可不填；填写后教师端可按学生汇总。')
        with subject_column:
            hint_index = SUBJECTS.index(st.session_state.get('subject', SUBJECTS[0])) \
                if st.session_state.get('subject') in SUBJECTS else 0
            photo_subject = st.selectbox('识别用学科提示', SUBJECTS, index=hint_index, key='photo_subject_hint')
        if st.button('识别照片内容', type='primary', key='photo_extract', disabled=not images):
            if photo_student.strip():
                st.session_state['student_name'] = photo_student.strip()[:30]
            _run_extraction(service, images, photo_subject)
        if not images:
            st.caption('先拍照或选择图片，才能开始识别。')
    _photo_result_panel(service)

    if st.button('填入数学示例'):
        _reset_form_state()
        st.session_state.update(subject='数学', question='解方程：2x + 3 = 11。',
                                student_answer='x = 7', correct_answer='x = 4',
                                student_thought='先把 3 移到右边，得到 2x = 14，再除以 2。')

    with st.form("diagnosis_form"):
        st.subheader("题目与作答")
        name_column, subject_column = st.columns([1, 2])
        with name_column:
            student_name = st.text_input("学生姓名（可选）", key="student_name", max_chars=30,
                                         placeholder='例如：张小明',
                                         help='填写后教师端可按学生汇总错题；留空记为“未署名”。')
        with subject_column:
            subject = st.selectbox("学科", SUBJECTS, key="subject")
        question = st.text_area("题目内容 *", height=120, key="question")
        answer_left, answer_right = st.columns(2)
        with answer_left:
            student_answer = st.text_area("学生答案 *", height=110, key="student_answer")
        with answer_right:
            correct_answer = st.text_area("正确答案 *", height=110, key="correct_answer")
        student_thought = st.text_area(
            "学生解题思路（可选）", height=100, key="student_thought"
        )
        if st.session_state.get('photo_recognized'):
            st.caption('以上内容来自照片识别，请核对后再提交；识别可能有误。')
        submitted = st.form_submit_button("开始诊断", type="primary", width="stretch")

    if submitted:
        missing = []
        if not question.strip():
            missing.append("题目内容")
        if not student_answer.strip():
            missing.append("学生答案")
        if not correct_answer.strip():
            missing.append("正确答案")
        if missing:
            st.error(f"请填写：{'、'.join(missing)}。")
        else:
            try:
                with st.spinner("正在分析错题并生成练习……"):
                    diagnosis = service.diagnose(
                        subject,
                        question,
                        student_answer,
                        correct_answer,
                        student_thought,
                    )
                    practices = service.generate_practices(subject, question, diagnosis)
                    diagnosis_data = diagnosis.model_dump()
                    practices_data = practices.model_dump()
                    photo_result = st.session_state.get('photo_result')
                    record_id = save_mistake(
                        subject=subject,
                        question=question,
                        student_answer=student_answer,
                        correct_answer=correct_answer,
                        student_thought=student_thought,
                        diagnosis=diagnosis_data,
                        practices=practices_data,
                        source_mode='演示数据' if service.is_mock_mode else '模型生成',
                        student_name=student_name,
                        photos=(photo_result or {}).get('photos'),
                    )
                st.session_state["latest_result"] = {
                    "record_id": record_id,
                    "diagnosis": diagnosis_data,
                    "practices": practices_data,
                }
                st.success("诊断完成，已保存到错题本。")
                if photo_result:
                    st.caption(f"本次连同 {len(photo_result['photos'])} 张作业照片一起保存，教师端可回看原卷。")
            except LLMServiceError as exc:
                st.error(str(exc))
                st.info("请检查 `.env` 配置；也可以暂时清空 OPENAI_API_KEY 使用演示模式。")
            except Exception as exc:
                st.error(f"保存或处理失败：{exc}")

    latest = st.session_state.get("latest_result")
    if latest:
        saved = get_mistake(latest['record_id'])
        if saved:
            latest['practices'] = saved['practices']
        st.divider()
        render_diagnosis(latest["diagnosis"])
        st.divider()
        render_practices(latest["practices"])


def main() -> None:
    st.set_page_config(page_title="课后错题诊断", page_icon="📘", layout="wide")
    design.apply_design()
    init_db()
    service = LLMService()

    with st.sidebar:
        design.brand()
    page = st.sidebar.radio("学习空间", PAGES, key='page')
    st.sidebar.divider()
    mode_text = "演示模式" if service.is_mock_mode else f"模型：{service.model}"
    st.sidebar.caption(mode_text)
    if not service.is_mock_mode:
        st.sidebar.caption('拍照识别：' + ('已启用' if service.vision_ready else '未配置多模态模型'))
    st.sidebar.caption('本地学习数据 · 自动保存')
    if service.is_mock_mode:
        st.sidebar.caption('AI 内容为演示示例，连接模型后启用真实分析。')

    if page == "错题诊断":
        _apply_result()
        render_submission_page(service)
    elif page == '错题本':
        ui.history(render_diagnosis, render_practices)
    elif page == '学习看板':
        ui.dashboard()
    elif page == '复习训练':
        ui.review(render_diagnosis, render_practices)
    elif page == '智能答疑':
        ui.tutor(service)
    elif page == '教师端':
        teacher.page(service)
    else:
        ui.help_page(service)


if __name__ == "__main__":
    main()
