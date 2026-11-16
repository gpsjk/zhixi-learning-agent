from database import delete_mistake, get_mistake, init_db, list_mistakes, save_mistake


def test_database_crud_round_trip(tmp_path):
    db_path = tmp_path / "mistakes.db"
    init_db(db_path)

    record_id = save_mistake(
        db_path=db_path,
        subject="数学",
        question="2+3=?",
        student_answer="4",
        correct_answer="5",
        student_thought="2+2=4",
        diagnosis={
            "is_correct": False,
            "knowledge_points": ["加法"],
            "error_type": "计算错误",
            "error_reason": "把3看成2",
        },
        practices={"exercises": []},
    )

    record = get_mistake(record_id, db_path)
    assert record is not None
    assert record["question"] == "2+3=?"
    assert record["knowledge_points"] == ["加法"]
    assert record["diagnosis"]["error_type"] == "计算错误"
    assert list_mistakes(db_path)[0]["id"] == record_id

    assert delete_mistake(record_id, db_path) is True
    assert get_mistake(record_id, db_path) is None


def test_list_mistakes_returns_newest_first(tmp_path):
    db_path = tmp_path / "mistakes.db"
    init_db(db_path)
    ids = []
    for question in ("第一题", "第二题"):
        ids.append(
            save_mistake(
                db_path=db_path,
                subject="数学",
                question=question,
                student_answer="",
                correct_answer="",
                student_thought="",
                diagnosis={"knowledge_points": [], "error_type": "计算错误"},
                practices={"exercises": []},
            )
        )
    assert [row["id"] for row in list_mistakes(db_path)] == list(reversed(ids))

