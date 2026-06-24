import pandas as pd
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(SCRIPT_DIR, 'data', 'merged_dedup_all3cols.xlsx')
CHECK_NUMBER = 10

# 未定义的 DDC 分类编号列表（字符串形式，如 '000', '099'）。
# 这些编号会被过滤掉，且不会出现在缺失分类统计中。
UNDEFINED_DDC = [
    '008', 
    '009', 
    '040', 
    '041',
    '042', 
    '043',
    '044',
    '045',
    '046',
    '047',
    '048',
    '049',
    '196',
    '434', 
    '436', 
    '444', 
    '446', 
    '454', 
    '456', 
    '464', 
    '466', 
    '474', 
    '476', 
    '484', 
    '486',
    '855',
    '865',
    '866',
    '094',
    '096',
    '167',
    '173',
    '038',
    '056',
    '090',
    '095',
    '037',
    '076',
    '176',
    '461',
    '053',
    '057',
    '058',
    '083',
    '088',
    '165',
    '847',
    '078',
    '867',
    '857',
    '035',
    '075',
    '097',
    '756'
]

print(f"读取: {INPUT_FILE} ...")
df = pd.read_excel(INPUT_FILE)

# ── 0. 过滤未定义 DDC 分类 ───────────────────────────────────────────
if UNDEFINED_DDC:
    undefined_set = set(str(v).strip() for v in UNDEFINED_DDC)
    before = len(df)
    df = df[~df['DDC'].astype(str).str.strip().str.zfill(3).isin(undefined_set)].reset_index(drop=True)
    print(f"已过滤未定义 DDC {sorted(undefined_set)}：{before} → {len(df)} 条")

# ── 1. DDC 统计（只看不足 CHECK_NUMBER 条的分类）────────────────────
ddc_counts = df.groupby('DDC').size().reset_index(name='count')
under_check_number = ddc_counts[ddc_counts['count'] < CHECK_NUMBER].copy()
under_check_number['gap_to_check_number'] = CHECK_NUMBER - under_check_number['count']
under_check_number = under_check_number.sort_values('DDC').reset_index(drop=True)

ddc_result = under_check_number.rename(columns={
    'DDC': 'ddc',
    'count': 'current_count',
    'gap_to_check_number': 'gap_to_check_number'
}).to_dict(orient='records')

# ── 2. Abstract/description 长度统计（单词数）─────────────────────────
desc_lengths = df['description'].astype(str).str.split().str.len()

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

undefined_int_set = {str(v).strip().zfill(3) for v in UNDEFINED_DDC if '.' not in str(v)}
all_ddc = {str(i).zfill(3) for i in range(1, 1000)} - undefined_int_set
existing_ddc = set(ddc_counts['DDC'].apply(pad_ddc))
# 只取纯整数三位码做对比（忽略带小数点的细分码）
existing_int_ddc = {d for d in existing_ddc if '.' not in d}
missing_ddc = sorted(all_ddc - existing_int_ddc)

# 将完全缺失的三位整数 DDC 作为 0 条记录并入不足 CHECK_NUMBER 的详情
missing_as_under_check_number = [
    {
        'ddc': code,
        'current_count': 0,
        'gap_to_check_number': CHECK_NUMBER
    }
    for code in missing_ddc
]

ddc_under_check_number_details = sorted(
    ddc_result + missing_as_under_check_number,
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
    # 排除未定义编号
    codes = [c for c in codes if c not in undefined_int_set]
    if not codes:
        continue
    under_check_number_mask = ddc_int_counts.loc[codes] < CHECK_NUMBER
    under_check_number_count = int(under_check_number_mask.sum())
    under_check_number_codes = [
        code for code in codes if bool(under_check_number_mask.loc[code])
    ]
    ddc_group_by_10.append({
        'ddc_range': f"{codes[0]}-{codes[-1]}",
        'under_check_number_count': under_check_number_count,
        'under_check_number_ddc_list': under_check_number_codes
    })

output = {
    'check_number': CHECK_NUMBER,
    'abstract_stats': abstract_stats,
    'ddc_under_check_number': {
        'total_ddc_classes': int(len(ddc_counts)),
        'ddc_over_check_number_count': int((ddc_counts['count'] >= CHECK_NUMBER).sum()),
        'ddc_over_check_number_total_records': int(ddc_counts[ddc_counts['count'] >= CHECK_NUMBER]['count'].sum()),
        'ddc_under_check_number_count': int(len(ddc_under_check_number_details)),
        'details': ddc_under_check_number_details
    },
    'ddc_group_by_10': ddc_group_by_10
}

output_path = os.path.join(SCRIPT_DIR, 'data', 'statistics.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"完成！结果已保存至: {output_path}")
print(f"\n── Abstract 统计（单词数）──")
print(f"  最多: {abstract_stats['max']} 词")
print(f"  最少: {abstract_stats['min']} 词")
print(f"  平均: {abstract_stats['mean']} 词")
print(f"\n── DDC 统计 ──")
print(f"  001-999 中完全缺失的分类: {len(missing_ddc)} 个")
print(f"  缺失列表: {missing_ddc[:20]}{'...' if len(missing_ddc) > 20 else ''}")
print(f"  总分类数: {output['ddc_under_check_number']['total_ddc_classes']}")
print(f"  >= {CHECK_NUMBER} 条的分类: {output['ddc_under_check_number']['ddc_over_check_number_count']} 个，共 {output['ddc_under_check_number']['ddc_over_check_number_total_records']} 条记录")
print(f"  < {CHECK_NUMBER} 条的分类:  {output['ddc_under_check_number']['ddc_under_check_number_count']}")
