import pandas as pd
import os
import re
# from langdetect import detect, LangDetectException  # 已注释，改用 fasttext
import fasttext
from dataclean import clean_text  # 复用已有的清洗逻辑

# 所有待合并的文件及其列映射
# 统一目标列：DDC, Title, description
FILES = [
    {
        'path': '0-49.xlsx',
        'rename': {},
    },
    {
        'path': '053to99.xlsx',
        'rename': {'DDC': 'DDC', 'title': 'Title', 'description': 'description'},
    },
    {
        'path': '104to169.xlsx',
        'rename': {},
    },
    {
        'path': '104to169_2.xlsx',
        'rename': {},
    },
    {
        'path': '213-298.xlsx',
        'rename': {},
    },
    {
        'path': '308 - 396.xlsx',
        'rename': {},
    },
    {
        'path': '403to474.xlsx',
        'rename': {'mds_code': 'DDC', 'title': 'Title', 'description': 'description'},
        'drop': ['bookid'],
    },
    {
        'path': '476to603.xlsx',
        'rename': {},
    },
    {
        'path': '605-765.xlsx',
        'rename': {},
    },
    {
        'path': '766-909.xlsx',
        'rename': {},
    },
    {
        'path': '910-940.xlsx',
        'rename': {},
    },
    {
        'path': '941-970.xlsx',
        'rename': {'mds_code': 'DDC', 'title': 'Title', 'description': 'description'},
    },
    {
        'path': '971-999.xlsx',
        'rename': {},
    },
    {
        'path': 'Lib_Dataset_Level3_26Nov25_final.xlsx',
        'rename': {'DDC-L3': 'DDC', 'Title': 'Title', 'Abstract': 'description'},
    },
]

TARGET_COLS = ['DDC', 'Title', 'description']
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOOK_DESC_PATTERN = re.compile(r'^book_descriptions_all(\d*)\.csv$', re.IGNORECASE)

# 未定义的 DDC 分类编号列表（字符串形式，如 '000', '099' 等）。
# 凡 DDC 值在此列表中的行将被过滤掉。
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

# 是否启用“仅保留英语描述”过滤。
# 这段逻辑用于剔除德语/法语等非英语摘要，适合只做英文数据集时开启。
# 默认关闭；如需启用改为 True。
ENABLE_ENGLISH_ONLY_FILTER = True


# ── 乱码检测辅助函数 ──────────────────────────────────────────────────
def _has_gbk_mojibake(text: str) -> bool:
    """检测文本是否包含 GBK 乱码特征（latin-1 → utf-8 重编码检测）。

    若文本中的 latin-1 字节能重新解码为有效的 utf-8 序列且结果不同，
    说明原始文本很可能是 UTF-8 字节被错误解释为单字节编码的产物。"""
    try:
        redecoded = text.encode('latin-1').decode('utf-8')
        return redecoded != text
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


def _detect_garbled_vectorized(df: pd.DataFrame) -> pd.Series:
    """矢量化乱码检测，综合三种规则：
    1. U+FFFD 替换字符
    2. C1 控制字符 (\\x80-\\x9F)
    3. GBK 乱码特征字符（latin-1 → utf-8 重编码检测）

    返回布尔 Series，True 表示该行包含乱码。"""
    title_str = df['Title'].astype(str)
    desc_str = df['description'].astype(str)

    # 规则1: U+FFFD 替换字符
    has_fffd = (
        title_str.str.contains('�', na=False, regex=False) |
        desc_str.str.contains('�', na=False, regex=False)
    )

    # 规则2: C1 控制字符 \x80-\x9F（可能是引号/破折号等被错误编码）
    has_c1 = (
        title_str.str.contains(r'[\x80-\x9f]', na=False, regex=True) |
        desc_str.str.contains(r'[\x80-\x9f]', na=False, regex=True)
    )

    # 规则3: GBK 乱码特征 — 先筛选出含 \x80-\xFF 字符的行，再逐行检测
    has_latin1_supp = (
        title_str.str.contains(r'[\x80-\xff]', na=False, regex=True) |
        desc_str.str.contains(r'[\x80-\xff]', na=False, regex=True)
    )
    has_gbk = pd.Series(False, index=df.index, dtype=bool)
    if has_latin1_supp.any():
        combined = title_str + ' ' + desc_str
        candidate_mask = has_latin1_supp & ~(has_fffd | has_c1)
        has_gbk[candidate_mask] = combined[candidate_mask].apply(_has_gbk_mojibake).astype(bool)

    return has_fffd | has_c1 | has_gbk


def get_auto_book_description_files():
    candidates = []
    for name in os.listdir(BASE_DIR):
        match = BOOK_DESC_PATTERN.match(name)
        if not match:
            continue
        suffix = match.group(1)
        # book_descriptions_all.csv 记为 1，book_descriptions_all2.csv 记为 2，以此类推
        order = 1 if suffix == '' else int(suffix)
        candidates.append((order, name))

    candidates.sort(key=lambda x: (x[0], x[1].lower()))
    return [
        {
            'path': name,
            'rename': {},
        }
        for _, name in candidates
    ]


def load_and_normalize(file_cfg):
    path = file_cfg['path']
    file_path = os.path.join(BASE_DIR, path)
    rename_map = file_cfg.get('rename', {})
    drop_cols = file_cfg.get('drop', [])

    print(f"  读取: {file_path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in ['.xlsx', '.xls']:
        df = pd.read_excel(file_path)
    elif ext == '.csv':
        df = pd.read_csv(file_path, encoding='utf-8-sig')
    else:
        raise ValueError(f"不支持的文件类型: {path}")

    df = df.drop(columns=[c for c in drop_cols if c in df.columns])

    if rename_map:
        df = df.rename(columns=rename_map)

    # 自动兼容常见列名差异（尤其是 book_descriptions_all*.csv）
    alias_map = {
        'mds_code': 'DDC',
        'ddc': 'DDC',
        'title': 'Title',
        'abstract': 'description',
        'desc': 'description',
    }
    auto_rename = {}
    for col in df.columns:
        normalized = str(col).strip().lower()
        if normalized in alias_map and alias_map[normalized] not in df.columns:
            auto_rename[col] = alias_map[normalized]
    if auto_rename:
        df = df.rename(columns=auto_rename)

    for col in TARGET_COLS:
        if col not in df.columns:
            df[col] = ''
    df = df[TARGET_COLS]

    return df


def main():
    auto_book_files = get_auto_book_description_files()
    files_to_load = FILES + auto_book_files

    all_dfs = []
    print("=== 第一步：读取并规范化各文件 ===")
    if auto_book_files:
        print(f"自动发现 book_descriptions_all 系列 CSV: {len(auto_book_files)} 个")
        for cfg in auto_book_files:
            print(f"  - {cfg['path']}")
    else:
        print("未发现 book_descriptions_all 系列 CSV")

    for cfg in files_to_load:
        df = load_and_normalize(cfg)
        all_dfs.append(df)
        print(f"    -> {len(df)} 条")

    print("\n=== 第二步：合并所有数据 ===")
    merged = pd.concat(all_dfs, ignore_index=True)
    print(f"合并后总计: {len(merged)} 条")

    print("\n=== 第二步（补）：文本清洗（Title + description）===")
    before_clean = len(merged)
    for col in ['Title', 'description']:
        merged[col] = merged[col].apply(clean_text)
    # 清洗后去掉 description 变为空或仅空白的行
    merged = merged[merged['description'].astype(str).str.strip() != ''].reset_index(drop=True)
    after_clean = len(merged)
    print(f"清洗前: {before_clean} 条 -> 清洗后: {after_clean} 条，去除 {before_clean - after_clean} 条（description 清洗后为空）")

    print("\n=== 第二步（补2）：过滤 abstract 少于 15 个词的行 ===")
    before_filter = len(merged)
    merged = merged[merged['description'].astype(str).str.split().str.len() >= 15].reset_index(drop=True)
    print(f"过滤前: {before_filter} 条 -> 过滤后: {len(merged)} 条，去除 {before_filter - len(merged)} 条")

    # 这段是“非英语过滤”逻辑：通过 fasttext 检测 description 语言，
    # 只保留英语（en）记录。当前默认不开启，避免误删数据。
    if ENABLE_ENGLISH_ONLY_FILTER:
        print("\n=== 第二步（补3）：过滤非英语行（用 fasttext 检测 description 语言）===")

        # fasttext 预训练语言识别模型（需先下载 lid.176.ftz）
        model_path = os.path.join(BASE_DIR, 'lid.176.ftz')
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"fasttext 语言模型未找到: {model_path}\n"
                "请从 https://fasttext.cc/docs/en/language-identification.html 下载 lid.176.ftz"
            )
        ft_model = fasttext.load_model(model_path)

        def is_english(text):
            text = str(text).strip()
            if not text:
                return False
            # fasttext 返回 (('__label__en',), array([0.99...]))
            label, conf = ft_model.predict(text.replace('\n', ' '), k=1)
            return label[0] == '__label__en'

        before_lang = len(merged)
        merged = merged[merged['description'].apply(is_english)].reset_index(drop=True)
        print(f"过滤前: {before_lang} 条 -> 过滤后: {len(merged)} 条，去除 {before_lang - len(merged)} 条")

        # 同样过滤非英文 Title
        before_title_filter = len(merged)
        merged = merged[merged['Title'].apply(is_english)].reset_index(drop=True)
        print(f"非英文标题过滤: 过滤前 {before_title_filter} 条 -> 过滤后 {len(merged)} 条，去除 {before_title_filter - len(merged)} 条")

        # # 旧版 langdetect 实现（已注释）：
        # def is_english(text):
        #     try:
        #         return detect(str(text)) == 'en'
        #     except LangDetectException:
        #         return False
    else:
        print("\n=== 第二步（补3）：非英语过滤已关闭（按配置跳过）===")

    if UNDEFINED_DDC:
        print(f"\n=== 第二步（补4）：过滤未定义 DDC 分类 ===")
        undefined_set = set(str(v).strip() for v in UNDEFINED_DDC)
        before_udf = len(merged)
        merged = merged[~merged['DDC'].astype(str).str.strip().apply(lambda x: x.split('.')[0].zfill(3)).isin(undefined_set)].reset_index(drop=True)
        after_udf = len(merged)
        print(f"过滤前: {before_udf} 条 -> 过滤后: {after_udf} 条，去除 {before_udf - after_udf} 条")
        print(f"过滤的 DDC: {sorted(undefined_set)}")
    else:
        print("\n=== 第二步（补4）：未定义 DDC 过滤已关闭（UNDEFINED_DDC 为空）===")

    print("\n=== 第三步：DDC 取整并补零 ===")
    before_ddc = len(merged)
    merged['DDC'] = (
        merged['DDC']
        .astype(str)
        .str.strip()
        .str.split('.')
        .str[0]
    )
    merged = merged[merged['DDC'].str.match(r'^\d+$')].reset_index(drop=True)
    merged['DDC'] = merged['DDC'].astype(int)
    merged['DDC'] = merged['DDC'].apply(lambda x: f"{x:03d}")
    merged = merged.sort_values(by='DDC').reset_index(drop=True)
    after_ddc = len(merged)
    print(f"DDC 取整: 过滤前 {before_ddc} 条 -> 过滤后 {after_ddc} 条，去除 {before_ddc - after_ddc} 条")
    print("排序完成")

    print("\n=== 第四步：去重（DDC + Title + description 三列全相同才删除）===")
    before = len(merged)
    merged = merged.drop_duplicates(subset=['DDC', 'Title', 'description']).reset_index(drop=True)
    after = len(merged)
    print(f"去重前: {before} 条 -> 去重后: {after} 条，减少 {before - after} 条")

    # 输出到 data 目录（当前脚本目录的上一级）
    output_dir = os.path.abspath(os.path.join(BASE_DIR, '..'))
    os.makedirs(output_dir, exist_ok=True)

    # ── 先保存未过滤版本（保留含乱码数据）──
    output = os.path.join(output_dir, 'merged_dedup_all3cols.xlsx')
    with pd.ExcelWriter(output, engine='xlsxwriter',
                        engine_kwargs={'options': {'strings_to_formulas': False}}) as writer:
        merged.to_excel(writer, index=False)
    print(f"\n未过滤版本已保存至: {output}")

    # ── 乱码检测并输出去乱码版本 ──
    print("\n=== 第五步：乱码检测并输出去乱码版本 ===")
    has_garbled = _detect_garbled_vectorized(merged)
    garbled_count = int(has_garbled.sum())
    total_count = len(merged)
    print(f"含乱码行数: {garbled_count} / {total_count}")
    merged_clean = merged[~has_garbled].reset_index(drop=True)
    print(f"排除乱码后: {len(merged_clean)} 条")

    output_clean = os.path.join(output_dir, 'merged_dedup_all3cols_clean.xlsx')
    with pd.ExcelWriter(output_clean, engine='xlsxwriter',
                        engine_kwargs={'options': {'strings_to_formulas': False}}) as writer:
        merged_clean.to_excel(writer, index=False)
    print(f"去乱码版本已保存至: {output_clean}")
    print(f"\n完成！")


if __name__ == '__main__':
    main()
