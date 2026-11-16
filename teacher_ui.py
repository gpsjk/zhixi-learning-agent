"""教师端：按班级汇总错题，统计高频错误知识点并生成讲评建议。

统计口径是本地错题记录，用于发现共同薄弱点，不等同于考试评分或能力测评。
"""
import base64
from datetime import date, datetime
import io
import json

import pandas as pd
import streamlit as st

import design
from database import list_mistakes, list_photos, list_students, teacher_stats
from llm_service import LLMService, LLMServiceError
from models import SUBJECTS

CHART_COLOR = '#167D8D'
TYPE_COLOR = '#D29A44'


def heading(title, subtitle):
    design.page_header(title, subtitle, 'TEACHER / 教师端')


def _safe_date(value, fallback):
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return fallback


def _filters(records):
    """返回 (筛选条件, 是否包含演示数据)。默认屏蔽演示数据，避免污染真实学情。"""
    today = date.today()
    earliest = min((_safe_date(r['created_at'], today) for r in records), default=today)
    names = [name for name in list_students() if name]
    with st.container(border=True):
        st.markdown('**统计筛选**')
        c1, c2, c3 = st.columns([1, 1, 2])
        student = c1.selectbox('学生', ['全部学生'] + names, key='teacher_student')
        subject = c2.selectbox('学科', ['全部学科'] + SUBJECTS, key='teacher_subject')
        span = c3.date_input('统计区间', value=(earliest, today), key='teacher_range')
        include_demo = st.toggle(
            '包含演示数据（source_mode = 演示数据）', value=False, key='teacher_include_demo',
            help='演示数据是模板生成的示例，默认不参与班级统计。'),
    if isinstance(span, (tuple, list)) and len(span) == 2:
        start, end = span
    elif isinstance(span, (tuple, list)) and len(span) == 1:
        start = end = span[0]
    else:
        start = end = span
    usable = records if include_demo else [r for r in records if r['source_mode'] != '演示数据']
    return {
        'subject': None if subject == '全部学科' else subject,
        'student': None if student == '全部学生' else student,
        'start': start.isoformat(),
        'end': end.isoformat(),
    }, usable, include_demo


def _chart(rows, label_column, value_column, color, empty_text):
    if not rows:
        st.caption(empty_text)
        return
    frame = pd.DataFrame(rows, columns=[label_column, value_column]).set_index(label_column)
    st.bar_chart(frame, color=color)


def _statistics_tab(stats, records):
    total = stats['total']
    cols = st.columns(4)
    for col, label, value in zip(cols, ['错题记录', '涉及学生', '高频知识点', '错误类型'],
                                 [total, stats['student_count'], len(stats['top_points']),
                                  len(stats['top_error_types'])]):
        col.metric(label, value, border=True)
    if not total:
        st.info('当前筛选范围内没有记录。可放宽时间区间、切换学科，或先让学生录入错题。')
        return
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader('错误最集中的知识点')
        _chart([(row['knowledge_point'], row['count']) for row in stats['top_points']],
               '知识点', '错题数', CHART_COLOR, '暂无知识点记录。')
    with right, st.container(border=True):
        st.subheader('涉及学生最多的知识点')
        _chart([(row['knowledge_point'], row['student_count']) for row in stats['top_points']],
               '知识点', '涉及学生数', TYPE_COLOR, '暂无学生数据。')
    st.subheader('知识点错题排行')
    st.dataframe(pd.DataFrame([
        {
            '知识点': row['knowledge_point'],
            '错题数': row['count'],
            '涉及学生数': row['student_count'],
            '占全部错题比例': f"{row['share'] * 100:.1f}%",
            '相关学科': '、'.join(row['subjects']) or '未标注',
        }
        for row in stats['top_points']
    ]), hide_index=True, width='stretch')
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader('错误类型分布')
        _chart([(row['error_type'], row['count']) for row in stats['top_error_types']],
               '错误类型', '错题数', TYPE_COLOR, '暂无错误类型记录。')
    with right, st.container(border=True):
        st.subheader('学科分布')
        _chart([(row['subject'], row['count']) for row in stats['by_subject']],
               '学科', '错题数', CHART_COLOR, '暂无学科记录。')
    if stats['by_student']:
        with st.container(border=True):
            st.subheader('学生错题量')
            st.dataframe(pd.DataFrame([
                {'学生': row['student'], '错题数': row['count']} for row in stats['by_student']
            ]), hide_index=True, width='stretch')
            st.caption('错题数量受录入次数影响，不能直接当作学生水平排名。')
    st.caption(f"统计范围：{stats['subject']} · {stats['student']} · "
               f"{stats['range']['start']} 至 {stats['range']['end']}，共 {total} 条记录。")


def _photo_bytes(photo):
    """还原照片字节；无法解码时返回 None，避免单张坏图打断整页统计。"""
    try:
        data = base64.b64decode(photo['image_base64'], validate=True)
    except (ValueError, TypeError, KeyError):
        return None
    if not data:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as opened:
            opened.verify()
    except ImportError:
        return data
    except Exception:
        return None
    return data


def _details_tab(stats, records):
    matched = [r for r in records if _in_scope(r, stats)]
    if not matched:
        st.info('当前筛选范围内没有记录。')
        return
    keyword = st.text_input('搜索题目或知识点', key='teacher_keyword')
    if keyword.strip():
        needle = keyword.strip().casefold()
        matched = [r for r in matched
                   if needle in (r['question'] + ' '.join(r['knowledge_points'])).casefold()]
    st.caption(f'匹配 {len(matched)} 条记录（按录入时间倒序）')
    for record in matched[:60]:
        name = record['student_name'] or '未署名'
        label = f"{name} · {record['subject']} · {record['question'][:38]}"
        if record['photo_count']:
            label = '📷 ' + label
        with st.expander(label):
            meta = [f"录入 {record['created_at'][:10]}", f"来源 {record['source_mode']}",
                    f"状态 {record['status']}", f"知识点 {'、'.join(record['knowledge_points'])}",
                    f"错误类型 {record['error_type']}"]
            st.caption(' · '.join(meta))
            st.write('**题目**')
            st.write(record['question'])
            left, right = st.columns(2)
            left.write('**学生答案**：' + (record['student_answer'] or '（未填写）'))
            right.write('**正确答案**：' + (record['correct_answer'] or '（未填写）'))
            if record['diagnosis'].get('error_reason'):
                st.write('**错因**：' + str(record['diagnosis']['error_reason']))
            if record['photo_count']:
                st.markdown('**学生上传的作业照片**')
                photos = list_photos(record['id'])
                columns = st.columns(min(len(photos), 3) or 1)
                for index, photo in enumerate(photos):
                    data = _photo_bytes(photo)
                    if data:
                        columns[index % len(columns)].image(data, caption=photo['name'] or f'照片 {index + 1}',
                                                            width='stretch')
                    else:
                        columns[index % len(columns)].caption(
                            f"{photo['name'] or '照片'}：原图无法显示，可能已损坏。")
                st.caption('照片保存在本地数据库，仅用于教师回看原卷。')


def _in_scope(record, stats):
    if stats['subject'] != '全部学科' and record['subject'] != stats['subject']:
        return False
    if stats['student'] != '全部学生' and (record['student_name'] or '未署名') != stats['student']:
        return False
    day = record['created_at'][:10]
    return stats['range']['start'] <= day <= stats['range']['end']


def _report_tab(service, stats, records):
    st.write('把当前筛选范围的统计结果交给模型，生成讲评课重点、课堂步骤和针对性练习。')
    st.caption('模型只接收知识点、错误类型和数量等统计信息，不包含学生答案原文。')
    if st.button('生成讲评建议', type='primary', key='teacher_report_button'):
        try:
            with st.spinner('正在根据统计结果整理讲评建议……'):
                report = service.build_teacher_report(_stats_payload(stats))
            st.session_state['teacher_report'] = report.model_dump()
        except LLMServiceError as exc:
            st.error(str(exc))
            st.info('请检查 `.env` 配置；也可以清空 OPENAI_API_KEY 使用演示模式查看统计摘要。')
    report = st.session_state.get('teacher_report')
    if not report:
        st.info('还没有生成讲评建议。统计与明细不依赖模型，可直接查看另外两个标签页。')
        return
    if report.get('summary'):
        st.subheader('本次主要问题')
        st.write(report['summary'])
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader('优先讲评知识点')
        for point in report.get('focus_points') or []:
            st.markdown(f'- {point}')
    with right, st.container(border=True):
        st.subheader('讲评课步骤')
        for index, step in enumerate(report.get('lesson_plan') or [], start=1):
            st.markdown(f'{index}. {step}')
    if report.get('advice'):
        st.subheader('跟进建议')
        for item in report['advice']:
            st.markdown(f'- {item}')
    exercises = report.get('exercises') or []
    if exercises:
        st.subheader('针对性练习')
        for index, exercise in enumerate(exercises, start=1):
            with st.expander(f"练习 {index} · {exercise.get('knowledge_point', '未标注知识点')}"):
                st.write(exercise.get('question', ''))
                st.markdown('**答案**：' + str(exercise.get('answer', '')))
                for number, step in enumerate(exercise.get('solution_steps') or [], start=1):
                    st.markdown(f'{number}. {step}')


def _stats_payload(stats):
    """只把统计数字交给模型，不带学生姓名与答案原文。"""
    return {
        'subject': stats['subject'],
        'student_scope': stats['student'],
        'range': stats['range'],
        'total': stats['total'],
        'student_count': stats['student_count'],
        'top_points': stats['top_points'],
        'top_error_types': stats['top_error_types'],
        'by_subject': stats['by_subject'],
    }


def _export_tab(stats, records):
    matched = [r for r in records if _in_scope(r, stats)]
    st.write('导出当前筛选范围的数据，用于教研组存档或进一步分析。')
    st.caption('导出内容包含学生姓名与作答原文，请注意隐私，不要公开传播。')
    rows = [{
        '记录号': r['id'],
        '学生': r['student_name'] or '未署名',
        '学科': r['subject'],
        '知识点': '、'.join(r['knowledge_points']),
        '错误类型': r['error_type'],
        '状态': r['status'],
        '照片数': r['photo_count'],
        '录入时间': r['created_at'],
        '题目': r['question'],
        '学生答案': r['student_answer'],
        '正确答案': r['correct_answer'],
    } for r in matched]
    left, right = st.columns(2)
    with left:
        st.download_button('导出统计汇总 JSON', json.dumps(_stats_payload(stats), ensure_ascii=False, indent=2),
                           '班级错题统计.json', 'application/json', key='teacher_export_stats')
    with right:
        st.download_button('导出错题明细 CSV', _to_csv(rows), '班级错题明细.csv', 'text/csv',
                           key='teacher_export_detail')
    st.subheader('错题明细预览')
    st.dataframe(pd.DataFrame(rows) if rows else pd.DataFrame([{'提示': '当前筛选范围没有记录'}]),
                 hide_index=True, width='stretch')


def _to_csv(rows):
    if not rows:
        return '提示\n当前筛选范围没有记录\n'
    frame = pd.DataFrame(rows)
    # Excel 默认按 GBK 打开 CSV，加 BOM 才能正确显示中文。
    return '\ufeff' + frame.to_csv(index=False)


def page(service: LLMService):
    heading('教师端 · 班级学情', '按知识点汇总全班错题，找出最需要集中讲评的部分。')
    all_records = list_mistakes()
    if not all_records:
        st.info('还没有任何错题记录。请先在“错题诊断”页面录入学生错题，教师端会自动汇总。')
        return
    filters, records, include_demo = _filters(all_records)
    stats = teacher_stats(subject=filters['subject'], student=filters['student'],
                          start=filters['start'], end=filters['end'])
    if not stats['total'] and not include_demo:
        st.warning('当前筛选范围内没有记录。默认已排除演示数据，可在筛选区打开“包含演示数据”查看示例统计。')
    tabs = st.tabs(['错题统计', '错题明细', '讲评建议', '数据导出'])
    with tabs[0]:
        _statistics_tab(stats, records)
    with tabs[1]:
        _details_tab(stats, records)
    with tabs[2]:
        _report_tab(service, stats, records)
    with tabs[3]:
        _export_tab(stats, records)
    st.caption('教师端为本地单人应用，仅统计本机数据库中的错题记录；'
               '样本量较小时结论有限，请结合课堂观察判断。')
