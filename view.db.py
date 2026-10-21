import sys
from pathlib import Path
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import sqlite3
import config
from datetime import datetime

conn = sqlite3.connect(config.DB_FILE_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. 打印todo_task表结构
print("========== todo_task 表字段结构 ==========")
cols = cur.execute("PRAGMA table_info(todo_task);").fetchall()
for c in cols:
    print(f"字段{c[0]} | {c[1]} | 类型：{c[2]}")

# 2. 查询所有任务，关联会议名称
print("\n========== 全部待办任务列表 ==========")
rows = cur.execute("""
SELECT t.task_id, t.meet_id, m.title meet_title, t.task_content, t.owner, t.deadline, t.priority, t.status, t.finish_at
FROM todo_task t LEFT JOIN meetings m ON t.meet_id = m.id ORDER BY t.deadline ASC;
""").fetchall()

if not rows:
    print("暂无任何待办任务数据")
else:
    for r in rows:
        print(f"""
任务ID：{r['task_id']}
所属会议ID：{r['meet_id']} | 会议名称：{r['meet_title']}
任务内容：{r['task_content']}
负责人：{r['owner']} | 截止日期：{r['deadline']} | 优先级：{r['priority']}
状态：{r['status']} | 完成时间：{r['finish_at']}
------------------------------------------""")
conn.close()