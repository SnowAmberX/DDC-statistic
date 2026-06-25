import pandas as pd
import re
from html import unescape

def clean_text(text):
    """
    Core cleaning logic: decode HTML entities, normalize whitespace,
    remove invisible characters, and strip wrapping quotes.
    """
    if pd.isna(text) or not isinstance(text, str):
        return text

    # ── 第1步：HTML 实体解码 ──
    # &amp; → &  &lt; → <  &#160; → 不间断空格  等等
    text = unescape(text)

    # ── 第2步：移除 HTML/XML 标签 ──
    text = re.sub(r'<[^>]*>', ' ', text)

    # ── 第3步：替换各种不可见/特殊空白字符为普通空格 ──
    text = text.replace('\u00a0', ' ')   # 不间断空格 (NBSP)
    text = text.replace('\u200b', '')    # 零宽空格
    text = text.replace('\u200c', '')    # 零宽非连接符
    text = text.replace('\u200d', '')    # 零宽连接符
    text = text.replace('\ufeff', '')    # BOM / 零宽不换行空格
    text = text.replace('\u2028', ' ')   # 行分隔符
    text = text.replace('\u2029', ' ')   # 段分隔符
    text = text.replace('\r\n', ' ')     # Windows 换行
    text = text.replace('\r', ' ')       # 老 Mac 换行
    text = text.replace('\n', ' ')       # Unix 换行
    text = text.replace('\t', ' ')       # 制表符

    # ── 第4步：移除 ASCII 控制字符（0x00-0x1f），保留已处理过的 \t\n\r ──
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

    # ── 第5步：规范化空白（连续多个空格合并为一个）──
    text = re.sub(r' {2,}', ' ', text)
    text = text.strip()

    # ── 第6步：移除首尾 wiki/markdown 格式标记 (= * # ~ _ |) ──
    text = re.sub(r'^[=\*#~_|]+', '', text)
    text = re.sub(r'[=\*#~_|]+$', '', text)
    text = text.strip()

    # ── 第7步：去掉配对的英文双引号包裹 ──
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].strip()

    # ── 第8步：去掉配对的中文双引号包裹 ──
    if len(text) >= 2 and text[0] == '\u201c' and text[-1] == '\u201d':
        text = text[1:-1].strip()

    return text

def process_excel_pro(input_file, output_file):
    # 读取 Excel 文件
    print(f"正在读取文件: {input_file}...")
    df = pd.read_excel(input_file)
    original_count = len(df)
    
    # --- 步骤 1: 去重 (完全重复的行) ---
    df = df.drop_duplicates().reset_index(drop=True)
    after_dedup_count = len(df)
    
    # --- 步骤 2: 文本清洗 ---
    # 对全表所有的字符串列进行清洗
    for col in df.columns:
        if df[col].dtype == 'object':  # 只处理文本类型的列
            df[col] = df[col].apply(clean_text)
            
    # --- 步骤 3: 再次去重 (防止清洗后产生的重复) ---
    # 比如两行原本因为乱码不同，清洗后变一模一样了，需再次去重
    df = df.drop_duplicates().reset_index(drop=True)
    final_count = len(df)
    
    # 保存结果
    df.to_excel(output_file, index=False)
    
    # 打印统计报告
    print("-" * 30)
    print(f"处理完成！报告如下：")
    print(f"1. 原始数据量: {original_count} 条")
    print(f"2. 剔除重复行及无效数据后: {final_count} 条")
    print(f"3. 总计减少: {original_count - final_count} 条")
    print(f"结果已保存至: {output_file}")

# --- 执行 ---
if __name__ == "__main__":
    # 请确保 book_descriptions910-940.xlsx 在当前目录下，或者填写完整路径
    process_excel_pro('book_descriptions910-940.xlsx', 'cleaned_output.xlsx')