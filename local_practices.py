"""Conservative local templates: never infer a topic from subject alone."""
import re
from models import PracticeExercise, PracticeSet

VERSION = 2


def local_practices(subject, question):
    q = re.sub(r'\s+', '', question).translate(str.maketrans({'（': '(', '）': ')', '，': ',', '＋': '+', '−': '-'}))
    if subject == '数学' and '定积分' in q and re.search(r'(?:f\(x\)=)?1/\(x\+[1-9]\d*\)', q):
        # Only the exact rational integrand family; unsupported combined expressions must not match.
        match = re.search(r'f\(x\)=1/\(x\+([1-9]\d*)\)(?=[，,。；;求它的在上]|$)', q)
        if match and not any(t in q for t in ('sin', 'cos', '反常', '二重', '三重', '无穷', '∞')):
            c = int(match[1])
            if c > 10000:
                return unavailable()
            bounds = re.search(r'\[(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\]', q)
            if not bounds or not (-c < float(bounds[1]) < float(bounds[2])):
                return unavailable()
            a = c + 1
            topic = '定积分：一次式倒数的积分'
            return PracticeSet(topic=topic, generator_version=VERSION, generation_mode='本地题型模板', exercises=[
                PracticeExercise(difficulty='基础题',
                    question=f'求定积分 $\\int_0^1 \\frac{{1}}{{x+{a}}}\\,dx$。请先写出原函数，再代入上下限。',
                    answer=f'$\\ln({a+1}/{a})$',
                    solution_steps=[f'在 [0,1] 上 x+{a}>0，原函数为 $\\ln(x+{a})$。',
                                    f'由微积分基本定理，积分等于 $\\ln({a+1})-\\ln({a})=\\ln({a+1}/{a})$。',
                                    '区间中点的函数值乘区间长度只是中点近似，不能直接当作精确积分。']),
                PracticeExercise(difficulty='变式题',
                    question=f'求定积分 $\\int_0^1 \\frac{{2}}{{2x+{a}}}\\,dx$。说明换元时积分上下限如何改变。',
                    answer=f'$\\ln({a+2}/{a})$',
                    solution_steps=[f'令 u=2x+{a}，则 du=2dx。',
                                    f'x=0 时 u={a}；x=1 时 u={a+2}。',
                                    f'积分变为 $\\int_{{{a}}}^{{{a+2}}}\\frac{{1}}{{u}}\\,du=\\ln({a+2}/{a})$。'])])
    # Only a complete elementary calculation prompt, never a numeric fragment in a higher-level question.
    simple = re.fullmatch(r'(?:计算[:：]?)?(\d{1,5})([+＋])(\d{1,5})(?:=)?[?？。]?', q)
    if subject == '数学' and simple:
        a, b = int(simple[1])+1, int(simple[3])+2
        return PracticeSet(topic='整数加法', generator_version=VERSION, generation_mode='本地题型模板', exercises=[
            PracticeExercise(difficulty='基础题', question=f'计算：{a}+{b}=?', answer=str(a+b), solution_steps=[f'将两数相加，得到 {a+b}。']),
            PracticeExercise(difficulty='变式题', question=f'填空：{a}+□={a+b+1}。', answer=str(b+1), solution_steps=[f'用和减去已知加数：{a+b+1}-{a}={b+1}。'])])
    return unavailable()


def unavailable():
    return PracticeSet(exercises=[], generator_version=VERSION, generation_mode='本地题型模板',
                       unavailable_reason='当前离线题型库无法可靠匹配这道题，未生成同类练习。请配置模型后重新生成。')
