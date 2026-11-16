import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent


def get_default_db_path() -> Path:
    configured = os.getenv("LEARNING_AGENT_DB_PATH", "").strip()
    return Path(configured) if configured else PROJECT_DIR / "data" / "mistakes.db"


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else get_default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: str | Path | None = None) -> None:
    with _connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mistakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                question TEXT NOT NULL,
                student_answer TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                student_thought TEXT NOT NULL DEFAULT '',
                knowledge_points TEXT NOT NULL,
                error_type TEXT NOT NULL,
                diagnosis_json TEXT NOT NULL,
                practices_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {r[1] for r in connection.execute('PRAGMA table_info(mistakes)')}
        additions = {
            'status': "TEXT NOT NULL DEFAULT '待复习'",
            'notes': "TEXT NOT NULL DEFAULT ''",
            'favorite': 'INTEGER NOT NULL DEFAULT 0',
            'next_review': "TEXT NOT NULL DEFAULT ''",
            'review_count': 'INTEGER NOT NULL DEFAULT 0',
            'streak': 'INTEGER NOT NULL DEFAULT 0',
            'source_mode': "TEXT NOT NULL DEFAULT '历史数据'",
            'student_name': "TEXT NOT NULL DEFAULT ''",
            'photo_count': 'INTEGER NOT NULL DEFAULT 0',
            'batch_id': "TEXT NOT NULL DEFAULT ''",
            'question_no': 'INTEGER NOT NULL DEFAULT 0',
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f'ALTER TABLE mistakes ADD COLUMN {name} {definition}')
        connection.execute('''CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, mistake_id INTEGER NOT NULL,
            rating TEXT NOT NULL, answer TEXT NOT NULL, created_at TEXT NOT NULL)''')
        connection.execute('''CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, mistake_id INTEGER NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)''')
        # 拍照上传的原图与转写结果，只保存在本地数据库，便于教师端回看原卷。
        connection.execute('''CREATE TABLE IF NOT EXISTS mistake_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, mistake_id INTEGER NOT NULL,
            name TEXT NOT NULL DEFAULT '', mime TEXT NOT NULL DEFAULT 'image/jpeg',
            image_base64 TEXT NOT NULL, extracted_json TEXT NOT NULL DEFAULT '{}',
            position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)''')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_mistake_photos_mistake ON mistake_photos (mistake_id)')
        connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_mistakes_batch_question
            ON mistakes (batch_id, question_no) WHERE batch_id <> '' AND question_no > 0""")
        # Preserve prior demo exercises for recovery; only repair explicitly labelled demo data.
        connection.execute('''CREATE TABLE IF NOT EXISTS practice_repair_backup (
            mistake_id INTEGER PRIMARY KEY, practices_json TEXT NOT NULL)''')
        for row in connection.execute("SELECT id,subject,question,practices_json FROM mistakes WHERE source_mode='演示数据'").fetchall():
            try:
                old = json.loads(row['practices_json'])
            except (ValueError, TypeError):
                continue
            if isinstance(old, dict) and old.get('generator_version') == 2:
                continue
            from local_practices import local_practices
            corrected = local_practices(row['subject'], row['question'])
            connection.execute('INSERT OR IGNORE INTO practice_repair_backup VALUES (?,?)', (row['id'], row['practices_json']))
            connection.execute('UPDATE mistakes SET practices_json=? WHERE id=?',
                               (corrected.model_dump_json(), row['id']))


def save_mistake(
    *,
    subject: str,
    question: str,
    student_answer: str,
    correct_answer: str,
    student_thought: str,
    diagnosis: dict[str, Any],
    practices: dict[str, Any],
    source_mode: str = '历史数据',
    student_name: str = '',
    photos: list[dict[str, Any]] | None = None,
    batch_id: str = '',
    question_no: int = 0,
    db_path: str | Path | None = None,
) -> int:
    init_db(db_path)
    batch_id = str(batch_id or '').strip()[:100]
    question_no = int(question_no or 0)
    if batch_id and question_no > 0:
        existing = find_batch_record(batch_id, question_no, db_path)
        if existing is not None:
            return int(existing['id'])
    knowledge_points = diagnosis.get("knowledge_points") or []
    error_type = str(diagnosis.get("error_type") or "基础知识不牢")
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    photo_rows = [photo for photo in (photos or []) if photo.get('image_base64')]
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO mistakes (
                subject, question, student_answer, correct_answer, student_thought,
                knowledge_points, error_type, diagnosis_json, practices_json, created_at,
                batch_id, question_no
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject,
                question,
                student_answer,
                correct_answer,
                student_thought,
                json.dumps(knowledge_points, ensure_ascii=False),
                error_type,
                json.dumps(diagnosis, ensure_ascii=False),
                json.dumps(practices, ensure_ascii=False),
                created_at,
                batch_id,
                question_no,
            ),
        )
        record_id = int(cursor.lastrowid)
        connection.execute('UPDATE mistakes SET source_mode = ?, student_name = ?, photo_count = ? WHERE id = ?',
                           (source_mode, student_name.strip(), len(photo_rows), record_id))
        for position, photo in enumerate(photo_rows):
            connection.execute('''INSERT INTO mistake_photos
                (mistake_id, name, mime, image_base64, extracted_json, position, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (record_id, str(photo.get('name', ''))[:120], str(photo.get('mime', 'image/jpeg')),
                 photo['image_base64'],
                 json.dumps(photo.get('extracted') or {}, ensure_ascii=False),
                 position, created_at))
        return record_id


def find_batch_record(batch_id: str, question_no: int,
                      db_path: str | Path | None = None) -> dict[str, Any] | None:
    """按稳定批次题号查找已保存记录；空批次不参与幂等匹配。"""
    normalized = str(batch_id or '').strip()
    number = int(question_no or 0)
    if not normalized or number <= 0:
        return None
    init_db(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            'SELECT * FROM mistakes WHERE batch_id = ? AND question_no = ?',
            (normalized, number),
        ).fetchone()
    return _deserialize(row) if row else None


def list_photos(record_id: int, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """返回某道错题保存的原图；用于教师端回看学生上传的作业照片。"""
    init_db(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            'SELECT id, name, mime, image_base64, extracted_json, position, created_at '
            'FROM mistake_photos WHERE mistake_id = ? ORDER BY position, id', (record_id,)
        ).fetchall()
    photos = []
    for row in rows:
        photo = dict(row)
        try:
            photo['extracted'] = json.loads(photo.pop('extracted_json'))
        except (ValueError, TypeError):
            photo['extracted'] = {}
        photos.append(photo)
    return photos


def list_students(db_path: str | Path | None = None) -> list[str]:
    """返回已录入错题的姓名列表，供教师端筛选。"""
    init_db(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT DISTINCT student_name FROM mistakes WHERE TRIM(student_name) <> '' ORDER BY student_name"
        ).fetchall()
    return [row['student_name'] for row in rows]


def teacher_stats(
    *,
    subject: str | None = None,
    student: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """按筛选条件汇总错题，产出教师端统计的结构化结果。

    统计口径为录入记录数，反映错题分布，不等同于考试得分或能力测评。
    """
    records = [r for r in list_mistakes(db_path) if _matches(r, subject, student, start, end)]
    point_counter: Counter = Counter()
    point_students: dict[str, set] = {}
    type_counter: Counter = Counter()
    subject_counter: Counter = Counter()
    student_counter: Counter = Counter()
    for record in records:
        subject_counter[record['subject']] += 1
        if record['student_name'].strip():
            student_counter[record['student_name']] += 1
        if record['diagnosis'].get('is_correct'):
            continue
        type_counter[record['error_type']] += 1
        for point in record['knowledge_points'] or ['未识别']:
            point_counter[point] += 1
            point_students.setdefault(point, set()).add(record['student_name'] or '未署名')
    total = len(records)
    top_points = [
        {
            'knowledge_point': point,
            'count': count,
            'share': round(count / total, 4) if total else 0.0,
            'student_count': len(point_students.get(point, set())),
            'subjects': sorted({r['subject'] for r in records
                                if (r['knowledge_points'] or ['未识别']) and point in (r['knowledge_points'] or ['未识别'])}),
        }
        for point, count in point_counter.most_common(limit)
    ]
    top_error_types = [
        {'error_type': error_type, 'count': count, 'share': round(count / total, 4) if total else 0.0}
        for error_type, count in type_counter.most_common(limit)
    ]
    return {
        'total': total,
        'student_count': len(student_counter),
        'student': student or '全部学生',
        'subject': subject or '全部学科',
        'range': {'start': start or '', 'end': end or ''},
        'top_points': top_points,
        'top_error_types': top_error_types,
        'by_subject': [{'subject': key, 'count': value} for key, value in subject_counter.most_common()],
        'by_student': [{'student': key, 'count': value} for key, value in student_counter.most_common(limit)],
    }


def _matches(record: dict[str, Any], subject: str | None, student: str | None,
             start: str | None, end: str | None) -> bool:
    if subject and record['subject'] != subject:
        return False
    if student and record['student_name'] != student:
        return False
    day = record['created_at'][:10]
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def _deserialize(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    record["knowledge_points"] = json.loads(record.pop("knowledge_points"))
    record["diagnosis"] = json.loads(record.pop("diagnosis_json"))
    record["practices"] = json.loads(record.pop("practices_json"))
    return record


def list_mistakes(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM mistakes ORDER BY id DESC"
        ).fetchall()
    return [_deserialize(row) for row in rows]


def get_mistake(
    record_id: int, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    init_db(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM mistakes WHERE id = ?", (record_id,)
        ).fetchone()
    return _deserialize(row) if row else None


def delete_mistake(record_id: int, db_path: str | Path | None = None) -> bool:
    init_db(db_path)
    with _connect(db_path) as connection:
        connection.execute('DELETE FROM reviews WHERE mistake_id = ?', (record_id,))
        connection.execute('DELETE FROM chat_messages WHERE mistake_id = ?', (record_id,))
        connection.execute('DELETE FROM mistake_photos WHERE mistake_id = ?', (record_id,))
        connection.execute('DELETE FROM practice_repair_backup WHERE mistake_id = ?', (record_id,))
        cursor = connection.execute("DELETE FROM mistakes WHERE id = ?", (record_id,))
        return cursor.rowcount > 0


def update_practices(record_id, practices, db_path=None):
    init_db(db_path)
    with _connect(db_path) as connection:
        cursor = connection.execute('UPDATE mistakes SET practices_json=? WHERE id=?',
                                    (json.dumps(practices, ensure_ascii=False), record_id))
        if not cursor.rowcount:
            raise ValueError('错题已不存在')


def update_notes(record_id, notes, favorite, db_path=None):
    init_db(db_path)
    with _connect(db_path) as connection:
        connection.execute('UPDATE mistakes SET notes=?, favorite=? WHERE id=?',
                           (notes, int(favorite), record_id))


def record_review(record_id, rating, answer, *, today=None, db_path=None):
    if rating not in ('忘记', '模糊', '掌握'):
        raise ValueError('无效的复习评价')
    today = today or date.today()
    init_db(db_path)
    with _connect(db_path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT streak FROM mistakes WHERE id=?', (record_id,)).fetchone()
        if row is None:
            raise ValueError('错题已不存在')
        streak = row['streak'] + 1 if rating == '掌握' else 0
        days = (3, 7, 14, 30)[min(streak - 1, 3)] if streak else {'忘记': 1, '模糊': 2}[rating]
        status = {'忘记': '待复习', '模糊': '巩固中', '掌握': '已掌握'}[rating]
        connection.execute('''UPDATE mistakes SET status=?, streak=?, next_review=?,
            review_count=review_count+1 WHERE id=?''',
            (status, streak, (today + timedelta(days=days)).isoformat(), record_id))
        connection.execute('INSERT INTO reviews (mistake_id,rating,answer,created_at) VALUES (?,?,?,?)',
                           (record_id, rating, answer, today.isoformat()))


def list_reviews(db_path=None):
    init_db(db_path)
    with _connect(db_path) as connection:
        return [dict(r) for r in connection.execute('SELECT * FROM reviews ORDER BY id DESC')]


def list_chat(record_id, db_path=None):
    init_db(db_path)
    with _connect(db_path) as connection:
        return [dict(r) for r in connection.execute(
            'SELECT role, content FROM chat_messages WHERE mistake_id=? ORDER BY id', (record_id,))]


def save_chat(record_id, question, answer, db_path=None):
    init_db(db_path)
    with _connect(db_path) as connection:
        if not connection.execute('SELECT id FROM mistakes WHERE id=?', (record_id,)).fetchone():
            raise ValueError('错题已不存在')
        for role, content in [('user', question), ('assistant', answer)]:
            connection.execute('''INSERT INTO chat_messages
                (mistake_id,role,content,created_at) VALUES (?,?,?,?)''',
                (record_id, role, content, datetime.now().astimezone().isoformat()))
