"""学习工作台页面；诊断渲染由原 app 模块通过参数复用。"""
from collections import Counter
from datetime import date
import json
import pandas as pd
import streamlit as st
import design

from database import (list_mistakes, delete_mistake, update_notes, record_review,
                      list_reviews, list_chat, save_chat)
from llm_service import LLMServiceError
from llm_service import LLMService
from models import Diagnosis
from database import update_practices


def due_records(records):
    return sorted([r for r in records if not r['next_review'] or r['next_review'] <= date.today().isoformat()],
                  key=lambda r: (r['next_review'], r['id']))


def go(page):
    st.session_state['page'] = page


def heading(title, subtitle):
    design.page_header(title, subtitle)


def dashboard():
    heading('学习概览', '查看近期积累，安排今天的复习。')
    design.hero()
    records = list_mistakes()
    due = due_records(records)
    mastered = sum(r['status'] == '已掌握' for r in records)
    reviews = list_reviews()
    cols = st.columns(4)
    for col, label, value in zip(cols, ['已收录题目', '今日待复习', '自评已掌握', '累计复习次数'],
                                 [len(records), len(due), mastered, len(reviews)]):
        col.metric(label, value, border=True)
    left, right = st.columns([2, 1])
    with left, st.container(border=True):
        st.subheader('今日学习任务')
        if due:
            st.write(f'有 {len(due)} 道题等待复习。先独立作答，再核对解题步骤。')
            for r in due[:3]:
                st.write(f"{r['subject']} · {r['question'][:70]}")
            st.button('开始今日复习', type='primary', on_click=go, args=('复习训练',))
        else:
            st.write('当前没有到期任务。可以录入新题，或提前巩固已有题目。')
        st.button('录入一道题', on_click=go, args=('错题诊断',))
    with right, st.container(border=True):
        st.subheader('掌握进度')
        st.progress(mastered / len(records) if records else 0)
        st.write(f'{mastered} / {len(records)} 道题自评掌握')
        st.caption('来自复习自评，不代表模型判分；已掌握题目仍会安排间隔复习。')
    if not records:
        st.info('还没有学习记录。从左侧“错题诊断”开始，也可以填入示例体验完整流程。')
        design.empty_guide()
        return
    a, b = st.columns(2)
    with a, st.container(border=True):
        st.subheader('学科分布')
        st.bar_chart(pd.DataFrame(Counter(r['subject'] for r in records).items(),
                                 columns=['学科', '题数']).set_index('学科'), color='#167D8D')
    with b, st.container(border=True):
        st.subheader('错误类型分布')
        counts = Counter(r['error_type'] for r in records if not r['diagnosis'].get('is_correct'))
        if counts:
            st.bar_chart(pd.DataFrame(counts.items(), columns=['类型', '题数']).set_index('类型'), color='#D29A44')
        else:
            st.caption('暂无错误类型记录。')
    st.caption('统计包含演示与历史数据，反映收录记录的分布；不作为能力测评结论。')
    with st.container(border=True):
        st.subheader('待巩固知识点')
        points = Counter(p for r in records if r['status'] != '已掌握' for p in r['knowledge_points'])
        if points:
            st.dataframe(pd.DataFrame(points.most_common(8), columns=['知识点', '待巩固题数']), hide_index=True)
        else:
            st.success('当前记录均已自评掌握，记得按时复习。')
    if reviews:
        st.subheader('复习活动')
        activity = Counter(r['created_at'][:10] for r in reviews)
        st.bar_chart(pd.DataFrame(sorted(activity.items()), columns=['日期', '次数']).set_index('日期'))


def export_markdown(records):
    parts = ['# 我的错题复习册\n']
    for r in records:
        d = r['diagnosis']
        parts.append(f"## {r['id']}. {r['subject']} · {r['status']}\n\n"
                     f"来源：{r['source_mode']}｜下次复习：{r['next_review'] or '待安排'}\n\n"
                     f"### 题目\n{r['question']}\n\n### 我的答案\n{r['student_answer']}\n\n"
                     f"### 参考答案\n{r['correct_answer']}\n\n### 诊断\n{d.get('error_reason', '')}\n\n"
                     f"### 解题步骤\n" + '\n'.join(f'{i}. {s}' for i, s in enumerate(d.get('solution_steps', []), 1)) +
                     f"\n\n### 反思笔记\n{r['notes']}\n")
        for e in r['practices'].get('exercises', []):
            parts.append(f"### 同类练习\n{e.get('question', '')}\n\n答案：{e.get('answer', '')}\n")
    return '\n'.join(parts)


def history(render_diagnosis, render_practices):
    heading('错题本', '把错因留下来，把方法带走。检索、收藏与复盘都在这里。')
    all_records = list_mistakes()
    if not all_records:
        st.info('错题本还是空的，请先提交一道错题。')
        return
    c1, c2, c3 = st.columns([2, 1, 1])
    keyword = c1.text_input('搜索题目、知识点或笔记', placeholder='例如：一元一次方程')
    subject = c2.selectbox('筛选学科', ['全部'] + sorted({r['subject'] for r in all_records}))
    status = c3.selectbox('掌握状态', ['全部', '待复习', '巩固中', '已掌握'])
    favorite = st.toggle('仅看收藏')
    records = [r for r in all_records if (subject == '全部' or r['subject'] == subject)
               and (status == '全部' or r['status'] == status) and (not favorite or r['favorite'])
               and keyword.strip().casefold() in (r['question'] + ' '.join(r['knowledge_points']) + r['notes']).casefold()]
    st.caption(f'找到 {len(records)} / {len(all_records)} 条记录')
    if not records:
        st.info('没有匹配记录，请调整筛选条件。')
        return
    with st.container(horizontal=True):
        st.download_button('导出复习册 Markdown', export_markdown(records), '错题复习册.md', 'text/markdown')
        st.download_button('导出所选题目 JSON', json.dumps(records, ensure_ascii=False, indent=2), '错题记录.json', 'application/json')
    page = st.number_input('页码（每页 10 条）', min_value=1, max_value=max(1, (len(records) + 9) // 10), step=1)
    for r in records[(page-1)*10:page*10]:
        rid = r['id']
        with st.expander(f"{'★ ' if r['favorite'] else ''}{r['subject']} · {r['question'][:45]} · {r['status']}"):
            st.caption(f"{r['created_at'][:10]} · {r['source_mode']} · 下次复习 {r['next_review'] or '尚未复习'}")
            st.write(r['question'])
            c1, c2 = st.columns(2)
            c1.write('我的答案：' + r['student_answer'])
            c2.write('参考答案：' + r['correct_answer'])
            if r['student_thought']:
                st.write('原解题思路：' + r['student_thought'])
            tabs = st.tabs(['诊断解析', '同类练习', '反思笔记'])
            with tabs[0]:
                render_diagnosis(r['diagnosis'])
            with tabs[1]:
                render_practices(r['practices'])
                if st.button('按原题重新生成练习', key=f'regenerate_{rid}'):
                    try:
                        with st.spinner('正在匹配原题知识点……'):
                            practices = LLMService().generate_practices(r['subject'], r['question'], Diagnosis.model_validate(r['diagnosis']))
                            update_practices(rid, practices.model_dump())
                        st.rerun()
                    except LLMServiceError as exc:
                        st.error(str(exc))
            with tabs[2], st.form(f'notes_{rid}'):
                notes = st.text_area('我的反思', r['notes'], key=f'notes_text_{rid}', max_chars=5000)
                fav = st.checkbox('收藏这道题', bool(r['favorite']))
                if st.form_submit_button('保存笔记与收藏'):
                    update_notes(rid, notes, fav)
                    st.rerun()
            confirmed = st.checkbox('确认删除本题及关联复习、答疑记录', key=f'confirm_{rid}')
            if st.button('删除这条记录', key=f'delete_{rid}', disabled=not confirmed):
                delete_mistake(rid)
                if st.session_state.get('latest_result', {}).get('record_id') == rid:
                    st.session_state.pop('latest_result', None)
                st.rerun()


def review(render_diagnosis, render_practices):
    heading('复习训练', '先独立作答，再看解析。用真实的自评安排下一次复习。')
    flash = st.session_state.pop('review_flash', None)
    if flash:
        st.success(flash)
    records = list_mistakes()
    scope = st.segmented_control('训练范围', ['今日到期', '全部题目'], default='今日到期')
    pool = due_records(records) if scope != '全部题目' else records
    if not pool:
        st.info('当前没有待复习题目。可切换“全部题目”提前巩固，或先录入新题。')
        return
    selected = st.selectbox('选择复习题目', [r['id'] for r in pool],
                            format_func=lambda rid: next(f"{r['subject']} · {r['question'][:55]}" for r in pool if r['id'] == rid))
    r = next(r for r in pool if r['id'] == selected)
    st.caption(f"{r['source_mode']} · 已复习 {r['review_count']} 次 · 当前状态：{r['status']}")
    with st.container(border=True):
        st.subheader('独立再做一次')
        st.write(r['question'])
        answer = st.text_area('这次的答案与思路', key=f'review_answer_{selected}', max_chars=5000)
        show = st.toggle('我已完成作答，查看参考解析', key=f'show_{selected}')
        if show:
            st.write('参考答案：' + r['correct_answer'])
            render_diagnosis(r['diagnosis'])
            rating = st.segmented_control('对照后自评', ['忘记', '模糊', '掌握'], key=f'rating_{selected}')
            st.caption('忘记：1 天后；模糊：2 天后；连续掌握：3 / 7 / 14 / 30 天后再复习。')
            if st.button('完成本次复习', type='primary', disabled=not rating):
                if not answer.strip():
                    st.error('请先填写本次答案与思路。')
                else:
                    record_review(selected, rating, answer.strip())
                    st.session_state['review_flash'] = '复习已记录，下次复习日期已更新。'
                    st.rerun()
    with st.expander('继续做同类练习'):
        render_practices(r['practices'])
        st.caption('同类练习可自行核对答案；上方复习自评记录对应原题。')


def tutor(service):
    heading('智能答疑', '围绕一道题继续追问，把不理解的每一步讲清楚。')
    records = list_mistakes()
    if not records:
        st.info('请先完成一道题的诊断，再来追问解题过程。')
        return
    rid = st.selectbox('选择要讨论的错题', [r['id'] for r in records],
                       format_func=lambda x: next(f"{r['subject']} · {r['question'][:55]}" for r in records if r['id'] == x))
    record = next(r for r in records if r['id'] == rid)
    with st.expander('本题上下文', expanded=True):
        st.write(record['question'])
        st.caption('知识点：' + '、'.join(record['knowledge_points']))
    st.caption('可以问：“为什么这一步要这样做？”“能换一种方法吗？”“先给我提示。”')
    messages = list_chat(rid)
    for message in messages:
        with st.chat_message(message['role']):
            st.write(message['content'])
    question = st.chat_input('输入你不理解的地方', max_chars=2000, key=f'chat_{rid}')
    if question:
        try:
            with st.spinner('正在整理讲解……'):
                answer = service.answer_followup(record, messages, question)
                save_chat(rid, question, answer)
            st.rerun()
        except LLMServiceError as exc:
            st.error(str(exc))


def help_page(service):
    heading('使用与设置', '了解工作台的学习流程与模型连接方式。')
    st.subheader('四步完成一次学习闭环')
    for title, body in [('01 · 诊断', '拍照上传作业照片自动识别，或手动输入完整题目、作答和参考答案；填写思路有助于定位第一处错误。'),
                        ('02 · 复盘', '在错题本查看解析、收藏重点题，记录自己的反思。'),
                        ('03 · 巩固', '到复习训练独立作答，自评后自动安排下次复习。'),
                        ('04 · 追问', '在智能答疑中选题，继续讨论不理解的步骤。')]:
        with st.container(border=True):
            st.markdown(f'**{title}**')
            st.write(body)
    st.subheader('教师端')
    st.write('教师端按学生、学科和时间区间汇总全班错题，给出错误最集中的知识点排行、'
             '涉及学生数、错误类型分布和错题明细，并可按需生成讲评建议。')
    st.caption('录入错题时填写“学生姓名”，教师端才能按学生汇总；留空记为“未署名”。'
               '教师端统计基于本地错题记录数量，不是考试成绩，也不能作为学生排名。')
    st.subheader('拍照识题')
    st.write('在错题诊断页用摄像头拍照或选择 JPG / PNG（最多 3 张），模型会转写题目、学生作答与解题过程，'
             '核对后回填表单。原图随错题保存在本地，教师端可回看原卷。')
    st.write('拍照识别需要支持图片输入的多模态模型：在 .env 中配置 OPENAI_VISION_MODEL。'
             '留空时沿用 OPENAI_MODEL；若该模型不支持图片，识别会给出提示，其他功能不受影响。')
    st.warning('识别结果必须人工核对后再用于诊断；字迹潦草、拍摄倾斜或光线不足时可能出错，'
               '模型也不会替你补全看不清的内容。')
    st.subheader('模型连接')
    st.write('当前：' + ('演示模式' if service.is_mock_mode else f'已配置模型 {service.model}'))
    st.write('将项目中的 .env.example 复制为 .env，填写 OPENAI_API_KEY 和 OPENAI_MODEL。'
             '使用兼容接口时同时填写 OPENAI_BASE_URL。保存后重启应用。')
    if not service.is_mock_mode:
        st.write('拍照识题：' + ('已启用，使用 ' + service.vision_model if service.vision_ready
                                else '未配置 OPENAI_VISION_MODEL，暂不可用。'))
    st.info('演示模式使用固定示例和模板，不会真正理解题意。接入模型后才会针对题目生成分析与答疑。')
    st.caption('本地单人使用；学习数据与作业照片保存在 data/mistakes.db。备份时请先停止应用再复制整个 data 文件夹。')
    st.caption('JSON 导出包含所选题目，不包含答疑、复习流水与照片；完整备份请使用数据库文件。')
    st.caption('教师端与其他导出包含学生姓名和作答原文，请注意隐私。')
