"""多题照片识别的纯数据状态转换，不依赖 Streamlit。"""

from copy import deepcopy
from typing import Any

from models import PhotoBatchExtraction


TEXT_FIELDS = ("question", "student_answer", "student_thought", "correct_answer")


def normalize_photo_batch(payload: dict[str, Any] | PhotoBatchExtraction,
                          image_count: int) -> dict[str, Any]:
    """把不可信模型输出转成稳定、可编辑的批次状态。"""
    batch = payload if isinstance(payload, PhotoBatchExtraction) else PhotoBatchExtraction.model_validate(payload)
    items = []
    for number, raw in enumerate(batch.items, start=1):
        item = raw.model_dump()
        original_sources = list(item.get("source_images") or [])
        valid_sources = sorted({source for source in original_sources if 1 <= source <= image_count})
        item.update(
            question_no=number,
            source_images=valid_sources,
            source_unknown=(not original_sources or len(valid_sources) != len(original_sources)),
            included=True,
            merged_into=None,
            saved_record_id=None,
            error="",
        )
        items.append(item)
    warnings = list(batch.warnings)
    if not items:
        items.append({
            "question_no": 1, "question": "", "student_answer": "",
            "student_thought": "", "correct_answer": "", "subject": "其他",
            "source_images": [], "source_unknown": True, "confidence_note": "",
            "warnings": [], "included": True, "merged_into": None,
            "saved_record_id": None, "error": "",
        })
        warnings.append("模型没有拆分出题目，请手动补充或重新识别。")
    return {"items": items, "warnings": warnings,
            "confidence_note": batch.confidence_note, "image_count": max(0, image_count)}


def _join_text(first: str, second: str) -> str:
    values = [value.strip() for value in (first, second) if isinstance(value, str) and value.strip()]
    return "\n".join(values)


def merge_adjacent_items(items: list[dict[str, Any]], source_index: int) -> list[dict[str, Any]]:
    """把目标题与下一道未消费题合并，返回新列表并保留来源不确定性。"""
    result = deepcopy(items)
    if source_index < 0 or source_index >= len(result):
        return result
    target = result[source_index]
    if target.get("merged_into") is not None:
        return result
    next_index = next((index for index in range(source_index + 1, len(result))
                       if result[index].get("merged_into") is None), None)
    if next_index is None:
        return result
    consumed = result[next_index]
    for field in TEXT_FIELDS:
        target[field] = _join_text(str(target.get(field, "")), str(consumed.get(field, "")))
    target["source_images"] = sorted(set(target.get("source_images") or []) |
                                      set(consumed.get("source_images") or []))
    target["source_unknown"] = bool(target.get("source_unknown") or consumed.get("source_unknown"))
    target["warnings"] = list(dict.fromkeys((target.get("warnings") or []) +
                                              (consumed.get("warnings") or [])))
    target["confidence_note"] = _join_text(str(target.get("confidence_note", "")),
                                             str(consumed.get("confidence_note", "")))
    consumed["included"] = False
    consumed["merged_into"] = target.get("question_no", source_index + 1)
    return result


def included_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回真正可提交的题目，不包含空题、排除题和被合并题。"""
    return [deepcopy(item) for item in items
            if item.get("included") is True and item.get("merged_into") is None
            and str(item.get("question", "")).strip()]
