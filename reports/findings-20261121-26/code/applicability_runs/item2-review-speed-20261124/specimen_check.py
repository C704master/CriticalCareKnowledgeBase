"""Conservative source-location reminder for definite respiratory-failure typing."""
import re
import unicodedata


def unmarked_oxygen(patient, claim):
    statement = unicodedata.normalize("NFKC", claim)
    if not re.search(r"(?:II?|[一二12])型呼吸衰竭",statement,re.I):
        return None
    if re.search(r"疑似|可能|考虑|待核|尚需|若|假如|不支持|无法|不能|排除|不符合|未证实|不宜|未能|未见",statement):
        return None
    if not re.search(r"本例|患者|表现为|符合|诊断为|确诊|判断为",statement):
        return None
    # A source marked arterial and carrying an actual reading suppresses this narrow reminder.
    arterial = r"(?:动脉(?:血)?氧分压|PaO2)(?:[（(][^）)\n]{1,15}[）)])?\s*[:：=]?\s*\d"
    candidates=[]
    for line in patient.splitlines():
        for clause in re.split(r"[；;。]",line):
            normalized=unicodedata.normalize("NFKC",clause)
            if re.search(arterial,normalized,re.I) or (
                re.search(r"动脉血气(?:分析)?",normalized)
                and re.search(r"氧分压(?:\([^)]{1,15}\))?\s*[:：=]?\s*\d",normalized)
            ):
                return None
            for match in re.finditer(r"氧分压(?:[（(][^）)\n]{1,15}[）)])?\s*[:：=]?\s*\d+(?:\.\d+)?[^；;。\n]{0,45}",clause):
                candidates.append(match.group(0))
    if not candidates:
        return None
    return {"reason":"本句确定了呼吸衰竭类型，已定位的氧分压读数缺少可核实的动脉标记。请核对标本和同期二氧化碳分压。","exact":candidates[-1:]}


def check_examples():
    claim="本例表现为Ⅰ型呼吸衰竭。"
    example="氧分压（体温）38.9mmHg；pCO₂偏低。"
    assert unmarked_oxygen(example,claim)
    assert unmarked_oxygen("静脉氧分压38mmHg",claim)
    for source,statement in [(example,"考虑Ⅰ型呼吸衰竭"),(example,"氧分压较前升高"),
                             (example+"动脉血氧分压 50mmHg",claim),
                             ("动脉血气：氧分压（体温）39mmHg",claim),
                             (example+"PaO₂: 50mmHg",claim),
                             ("仅记氧疗中",claim)]:
        assert unmarked_oxygen(source,statement) is None
