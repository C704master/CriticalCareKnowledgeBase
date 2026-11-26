"""Resolve dated observations and quantitative administration claims against cited records."""
import re
from datetime import date, timedelta


REVIEW_VERSION = "V8_审稿附栏目标题"
ANSWER_VERSION = "V9_审稿附栏目标题"
HEADER = re.compile(r"【(\d{4}-\d{2}-\d{2}) ([^】]+)】")
OBSERVATION = re.compile(
    r"(?<![\d年])(?P<m>\d{1,2})月(?P<d>\d{1,2})日(?:至|到|—|–)"
    r"(?:(?P<m2>\d{1,2})月)?(?P<d2>\d{1,2})日(?:持续|连续)"
    r"(?P<term>[\u4e00-\u9fff]{2,12})(?=[，。；,;]|$)"
)
DOSE_OR_TIME = re.compile(
    r"\d{1,2}[:：]\d{2}|\d(?:\.\d+)?\s*(?:mg|[μµu]g|g|ml|iu|毫克|克|毫升|片|单位)", re.I
)
NUM = re.compile(r"(?<![a-zA-Z\d.])\d+(?:\.\d+)?(?![\d.])")


def record_context(patient):
    """Index section labels separately from event dates; rounds can quote an earlier day."""
    result = {}
    heading = ""
    for index, line in patient.items():
        if line.startswith("【"):
            heading = line
        match = HEADER.fullmatch(heading)
        day = None
        section = match[2] if match else ""
        if section in {"monitoring_data", "orders_execution"}:
            day = date.fromisoformat(match[1])
        elif heading.startswith("【摘要"):
            prefix = re.match(r"^(\d{4}-\d{2}-\d{2})[：:]", line)
            if prefix:
                day = date.fromisoformat(prefix[1])
        result[index] = (heading, section, day)
    return result


def line_number(key):
    return int(key.split(".")[0][1:])


def check_span(match, dated_quotes):
    term = match["term"]
    dates = {day for day, quote in dated_quotes if day and term in quote}
    month, first = int(match["m"]), int(match["d"])
    for start in dates:
        if (start.month, start.day) != (month, first):
            continue
        end_month = int(match["m2"] or month)
        end = date(start.year + (end_month < month), end_month, int(match["d2"]))
        days = (end - start).days + 1
        if 0 < days <= len(dates) and all(start + timedelta(days=i) in dates for i in range(days)):
            return ""
    raise ValueError(f"所引记录未逐日覆盖{match[0]}")


def validate_record_claim(row, patient_pieces, knowledge_pieces, context):
    """Return publishable wording and an audit trail without changing the model response."""
    if row["处置"] == "删除":
        return row, None
    keys = row["病历片段"]
    body = row["内容"].strip()
    sources = [(context[line_number(k)], patient_pieces[k]) for k in keys]
    orders = [k for k in keys if context[line_number(k)][1] == "orders_execution"]
    if orders and DOSE_OR_TIME.search(body):
        # Free prose can distribute one time across multiple drugs or transpose two days.
        # Emit only the selected administration rows, each under its own dated heading.
        tail = body.rsplit("；", 1)[-1]
        pending = tail.startswith("需核实") and not re.search(r"\d", tail) and "。" not in tail.rstrip("。")
        follow_up = tail if pending else "相关临床判断需结合当时的观察核实。"
        safe = dict(row, 内容="具体给药时间和剂量见所引执行记录。"+follow_up,
                    类型="待核实", 处置="改写", 病历片段=keys if pending else orders,
                    知识片段=row["知识片段"] if pending else [])
        return safe, {"动作":"拦截自由复述，按给药记录逐条呈现","原句":body,"记录":orders}
    dated_quotes = [(meta[2], quote) for meta, quote in sources]
    remaining = OBSERVATION.sub(lambda m: check_span(m, dated_quotes), body)
    source_text = " ".join([q for _, q in sources] + [knowledge_pieces[k] for k in row["知识片段"]])
    for number in NUM.findall(remaining):
        if not re.search(r"(?<![\d.])" + re.escape(number) + r"(?![\d.])", source_text):
            raise ValueError(f"来源未给出的数字：{number}")
    return row, {"动作":"逐日定位","原句":body} if body != remaining else None
