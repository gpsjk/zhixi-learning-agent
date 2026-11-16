from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SUBJECTS = ["数学", "语文", "英语", "物理", "化学", "生物", "历史", "地理", "政治", "其他"]


ERROR_TYPES = (
    "概念错误",
    "审题错误",
    "计算错误",
    "公式使用错误",
    "方法选择错误",
    "步骤缺失",
    "粗心错误",
    "基础知识不牢",
)


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_correct: bool = False
    knowledge_points: list[str] = Field(default_factory=lambda: ["未识别"])
    correct_parts: list[str] = Field(default_factory=list)
    first_error: str = "未定位到明确步骤"
    error_type: str = "基础知识不牢"
    error_reason: str = "需要结合完整解题过程进一步判断"
    solution_idea: str = "先理解题意，再根据正确答案逐步核对。"
    solution_steps: list[str] = Field(
        default_factory=lambda: ["梳理已知条件", "按正确方法完成计算或推理", "检查答案"]
    )
    warning: str = "完成后请回代或复查关键步骤。"

    @field_validator("error_type", mode="before")
    @classmethod
    def normalize_error_type(cls, value: Any) -> str:
        return value if value in ERROR_TYPES else "基础知识不牢"

    @field_validator("knowledge_points", "solution_steps", mode="before")
    @classmethod
    def normalize_required_lists(cls, value: Any, info) -> list[str]:
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return [str(item).strip() for item in value if str(item).strip()]
        if info.field_name == "knowledge_points":
            return ["未识别"]
        return ["梳理已知条件", "按正确方法完成计算或推理", "检查答案"]


class PracticeExercise(BaseModel):
    model_config = ConfigDict(extra="ignore")

    difficulty: str = "基础题"
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    solution_steps: list[str] = Field(min_length=1)

    @field_validator("solution_steps", mode="before")
    @classmethod
    def normalize_steps(cls, value: Any) -> list[str]:
        if not isinstance(value, list) or not value or any(not isinstance(s, str) or not s.strip() for s in value):
            raise ValueError('练习必须包含非空解题步骤')
        return value

    @field_validator('question', 'answer')
    @classmethod
    def nonempty_text(cls, value):
        if not value.strip():
            raise ValueError('题目与答案不能为空')
        return value.strip()


class PracticeSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    exercises: list[PracticeExercise] = Field(default_factory=list)
    topic: str = ''
    unavailable_reason: str = ''
    generation_mode: str = '模型生成'
    generator_version: int = 2

    @model_validator(mode="after")
    def ensure_two_exercises(self):
        if not self.exercises and self.unavailable_reason.strip():
            return self
        if len(self.exercises) != 2:
            raise ValueError('必须返回两道完整练习，不能用占位内容补齐')
        self.exercises[0].difficulty = "基础题"
        self.exercises[1].difficulty = "变式题"
        return self


class PhotoExtraction(BaseModel):
    """作业照片的转写结果；只描述照片中真实可见的内容。"""

    model_config = ConfigDict(extra="ignore")

    question: str = ""
    student_answer: str = ""
    student_thought: str = ""
    subject: str = "其他"
    warnings: list[str] = Field(default_factory=list)

    @field_validator("question", "student_answer", "student_thought", mode="before")
    @classmethod
    def text_or_empty(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("subject", mode="before")
    @classmethod
    def known_subject(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip()
        return text if text in SUBJECTS else "其他"

    @field_validator("warnings", mode="before")
    @classmethod
    def keep_text_warnings(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]


class PhotoItemExtraction(BaseModel):
    """批量照片中拆分出的单道题，只保留照片中可见的信息。"""

    model_config = ConfigDict(extra="ignore")

    question_no: int = 0
    question: str = ""
    student_answer: str = ""
    student_thought: str = ""
    correct_answer: str = ""
    subject: str = "其他"
    source_images: list[int] = Field(default_factory=list)
    confidence_note: str = ""
    warnings: list[str] = Field(default_factory=list)

    @field_validator(
        "question", "student_answer", "student_thought", "correct_answer",
        "confidence_note", mode="before",
    )
    @classmethod
    def item_text_or_empty(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("subject", mode="before")
    @classmethod
    def item_known_subject(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip()
        return text if text in SUBJECTS else "其他"

    @field_validator("source_images", mode="before")
    @classmethod
    def valid_source_numbers(cls, value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        numbers = []
        for raw in value:
            try:
                number = int(raw)
            except (TypeError, ValueError):
                continue
            if number > 0 and number not in numbers:
                numbers.append(number)
        return sorted(numbers)

    @field_validator("warnings", mode="before")
    @classmethod
    def item_warnings(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]


class PhotoBatchExtraction(BaseModel):
    """一次多图片识别返回的多题批次。"""

    model_config = ConfigDict(extra="ignore")

    items: list[PhotoItemExtraction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence_note: str = ""

    @field_validator("warnings", mode="before")
    @classmethod
    def batch_warnings(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("confidence_note", mode="before")
    @classmethod
    def batch_confidence(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()


class TeacherExercise(BaseModel):
    """教师端讲评课使用的针对性练习。"""

    model_config = ConfigDict(extra="ignore")

    knowledge_point: str = "未标注知识点"
    question: str
    answer: str
    solution_steps: list[str] = Field(default_factory=list)

    @field_validator("question", "answer", mode="before")
    @classmethod
    def nonempty_required(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip()
        if not text:
            raise ValueError("讲评练习的题目与答案不能为空")
        return text


class TeacherReport(BaseModel):
    """教师端讲评建议；用于把统计结果转成可执行的讲评方案。"""

    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    focus_points: list[str] = Field(default_factory=list)
    lesson_plan: list[str] = Field(default_factory=list)
    exercises: list[TeacherExercise] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
