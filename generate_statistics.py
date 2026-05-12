import pandas as pd
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(SCRIPT_DIR, 'data', 'merged_dedup_all3cols.xlsx')
CHECK_NUMBER = 10

print(f"读取: {INPUT_FILE} ...")
df = pd.read_excel(INPUT_FILE)

# ── 1. DDC 统计（只看不足 100 条的分类）──────────────────────────────
ddc_counts = df.groupby('DDC').size().reset_index(name='count')
under_100 = ddc_counts[ddc_counts['count'] < CHECK_NUMBER].copy()
under_100['gap_to_100'] = CHECK_NUMBER - under_100['count']
under_100 = under_100.sort_values('DDC').reset_index(drop=True)

ddc_result = under_100.rename(columns={
    'DDC': 'ddc',
    'count': 'current_count',
    'gap_to_100': 'gap_to_100'
}).to_dict(orient='records')

# ── 2. Abstract/description 长度统计 ─────────────────────────────────
desc_lengths = df['description'].astype(str).str.len()

abstract_stats = {
    'max': int(desc_lengths.max()),
    'min': int(desc_lengths.min()),
    'mean': round(float(desc_lengths.mean()), 2),
    'total_records': len(df)
}

# ── 3. 汇总输出 ───────────────────────────────────────────────────────
# 找出 001-999 中完全缺失的 DDC（整数部分补零后比对）
def pad_ddc(val):
    val = str(val).strip()
    if '.' in val:
        integer, decimal = val.split('.', 1)
        return integer.zfill(3) + '.' + decimal
    return val.zfill(3)

def ddc_int_code(val):
    return pad_ddc(val).split('.', 1)[0]

all_ddc = {str(i).zfill(3) for i in range(1, 1000)}
existing_ddc = set(ddc_counts['DDC'].apply(pad_ddc))
# 只取纯整数三位码做对比（忽略带小数点的细分码）
existing_int_ddc = {d for d in existing_ddc if '.' not in d}
missing_ddc = sorted(all_ddc - existing_int_ddc)

# 将完全缺失的三位整数 DDC 作为 0 条记录并入 under_100 详情
missing_as_under_100 = [
    {
        'ddc': code,
        'current_count': 0,
        'gap_to_100': 100
    }
    for code in missing_ddc
]

ddc_under_100_details = sorted(
    ddc_result + missing_as_under_100,
    key=lambda item: (item['current_count'], pad_ddc(item['ddc']))
)

# 每 10 个 DDC 一组的记录数统计（000-009, 010-019, ..., 990-999）
all_int_ddc = [str(i).zfill(3) for i in range(0, 1000)]
ddc_int_counts = (
    df['DDC']
    .apply(ddc_int_code)
    .value_counts()
    .reindex(all_int_ddc, fill_value=0)
)

ddc_group_by_10 = []
for i in range(0, 1000, 10):
    codes = [str(j).zfill(3) for j in range(i, i + 10)]
    ddc_group_by_10.append({
        'ddc_range': f"{codes[0]}-{codes[-1]}",
        'total_records': int(ddc_int_counts.loc[codes].sum())
    })

output = {
    'abstract_stats': abstract_stats,
    'ddc_under_100': {
        'total_ddc_classes': int(len(ddc_counts)),
        'ddc_over_100_count': int((ddc_counts['count'] >= 100).sum()),
        'ddc_over_100_total_records': int(ddc_counts[ddc_counts['count'] >= 100]['count'].sum()),
        'ddc_under_100_count': int(len(ddc_under_100_details)),
        'details': ddc_under_100_details
    },
    'ddc_group_by_10': ddc_group_by_10
}

output_path = os.path.join(SCRIPT_DIR, 'data', 'statistics.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"完成！结果已保存至: {output_path}")
print(f"\n── Abstract 统计 ──")
print(f"  最长: {abstract_stats['max']} 字符")
print(f"  最短: {abstract_stats['min']} 字符")
print(f"  平均: {abstract_stats['mean']} 字符")
print(f"\n── DDC 统计 ──")
print(f"  001-999 中完全缺失的分类: {len(missing_ddc)} 个")
print(f"  缺失列表: {missing_ddc[:20]}{'...' if len(missing_ddc) > 20 else ''}")
print(f"  总分类数: {output['ddc_under_100']['total_ddc_classes']}")
print(f"  >= 100 条的分类: {output['ddc_under_100']['ddc_over_100_count']} 个，共 {output['ddc_under_100']['ddc_over_100_total_records']} 条记录")
print(f"  < 100 条的分类:  {output['ddc_under_100']['ddc_under_100_count']}")
