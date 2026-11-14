from .validation import require_tables, unique, finite, references


SCHEMA = {'readings': {'reading': ['str'], 'meter_id': ['str'], 'day': ['number'], 'cumulative': ['null', 'number'], 'quality': ['str']}, 'operations': {'operation': ['str'], 'site': ['str'], 'day': ['number'], 'temperature': ['number'], 'service_hours': ['number'], 'users': ['number'], 'period': ['str']}, 'meters': {'meter_id': ['str'], 'site': ['str'], 'meter': ['str'], 'boundary': ['str'], 'multiplier_before': ['number'], 'multiplier_after': ['number'], 'replacement_day': ['number'], 'sub_of': ['null', 'str']}, 'adjustments': {'adjustment': ['str'], 'site': ['str'], 'start': ['number'], 'stop': ['number'], 'kind': ['str'], 'approved': ['boolean'], 'impact_kwh': ['null', 'number']}}
OPTIONS = {'site': ['A', 'B'], 'meter': ['main', 'sub']}


def validate_structure(data, schema):
    require_tables(data, list(schema))
    for table, fields in schema.items():
        for row in data[table]:
            if not isinstance(row, dict) or any(field not in row for field in fields):
                raise ValueError("表字段缺失：" + table)
            for field, kinds in fields.items():
                value = row[field]
                kind = "null" if value is None else ("boolean" if isinstance(value,bool) else ("number" if isinstance(value,(int,float)) else type(value).__name__))
                if kind not in kinds:
                    raise ValueError("字段类型错误：" + table + "." + field)
                if kind == "number":
                    finite(value)


def validate(data):
    validate_structure(data, SCHEMA)
    unique(data['readings'], ['reading'])
    unique(data['operations'], ['operation'])
    unique(data['meters'], ['meter_id'])
    unique(data['adjustments'], ['adjustment'])
    references(data['readings'], 'meter_id', data['meters'], 'meter_id')
    for row in data["readings"]:
        if (row["quality"] == "missing") != (row["cumulative"] is None):
            raise ValueError("缺表标记与读数不符")
        if row["cumulative"] is not None:
            finite(row["cumulative"], minimum=0)


def view(rows, measure, note):
    return {"summary":{"明细条数":len(rows),"有数值记录":sum(isinstance(row.get(measure),(int,float)) for row in rows)},
            "rows":rows,"series":[{"label":str(position+1),"y":row.get(measure)} for position,row in enumerate(rows)],
            "notes":[note]}


def explore(data, selection):
    for key, choices in OPTIONS.items():
        if selection.get(key) not in choices:
            raise ValueError("选择范围无效：" + key)
    meter = next(row for row in data["meters"] if row["site"] == selection["site"] and row["meter"] == selection["meter"])
    rows = []
    previous = None
    for reading in sorted([row for row in data["readings"] if row["meter_id"] == meter["meter_id"]], key=lambda row:row["day"]):
        raw = reading["cumulative"]-previous if previous is not None and reading["cumulative"] is not None else None
        rows.append({**reading,"raw_delta":raw})
        previous = reading["cumulative"]
    return view(rows, "raw_delta", "原始差分未校正倍率和换表重置，仅用于核对表盘，不能作为能耗或节能结论。")
