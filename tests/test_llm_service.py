import json

import pytest

from llm_service import LLMService, LLMServiceError, parse_json_object
from models import Diagnosis


def test_parse_json_object_accepts_markdown_code_fence():
    payload = {"is_correct": True, "knowledge_points": ["一元一次方程"]}
    parsed = parse_json_object(f"以下是结果：\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```")
    assert parsed == payload


def test_diagnosis_fills_missing_fields():
    diagnosis = Diagnosis.model_validate({"is_correct": False})
    assert diagnosis.error_type == "基础知识不牢"
    assert diagnosis.solution_steps
    assert diagnosis.knowledge_points


def test_diagnosis_normalizes_unknown_error_type():
    diagnosis = Diagnosis.model_validate({"error_type": "未知类别"})
    assert diagnosis.error_type == "基础知识不牢"


def test_missing_api_key_uses_mock_data(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = LLMService(api_key="")
    diagnosis = service.diagnose(
        subject="数学",
        question="2+3=?",
        student_answer="4",
        correct_answer="5",
        student_thought="2+2=4",
    )
    practices = service.generate_practices("数学", "2+3=?", diagnosis)
    assert service.is_mock_mode is True
    assert diagnosis.is_correct is False
    assert len(practices.exercises) == 2
    assert practices.exercises[0].difficulty == "基础题"
    assert practices.exercises[1].difficulty == "变式题"
    assert all("演示模式" not in item.answer for item in practices.exercises)
    assert all(item.question != "2+3=?" for item in practices.exercises)


class _BrokenCompletions:
    def create(self, **kwargs):
        raise RuntimeError("network down")


class _BrokenClient:
    class _Chat:
        completions = _BrokenCompletions()

    chat = _Chat()


def test_api_failure_becomes_readable_service_error():
    service = LLMService(api_key="test-key", model="test-model", client=_BrokenClient())
    with pytest.raises(LLMServiceError, match="大模型请求失败"):
        service.diagnose("数学", "1+1", "3", "2", "")
