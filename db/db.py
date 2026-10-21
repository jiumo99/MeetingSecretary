import sqlite3
import os
import shutil
from datetime import datetime
import config
from utils.logger import get_logger

logger = get_logger("db")
DB_PATH = config.DB_FILE_PATH
BACKUP_DIR = config.DB_BACKUP_ROOT

def init_db():
    """初始化数据表，升级会议表 + 新增独立待办任务表"""
    BACKUP_DIR.mkdir(exist_ok=True, parents=True)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # 1. 主会议表（新增多维检索字段）
            conn.execute("""
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                meeting_type TEXT,
                audio_path TEXT,
                transcript TEXT,
                summary TEXT,
                todos TEXT,
                todo_person TEXT,
                keyword_tags TEXT,
                is_archive INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            # 2. 独立待办任务明细表（一对多关联会议）
            conn.execute("""
            CREATE TABLE IF NOT EXISTS todo_task (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                meet_id INTEGER NOT NULL,
                task_content TEXT,
                owner TEXT,
                deadline TEXT,
                priority TEXT,
                status TEXT DEFAULT "待处理",
                create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finish_at TEXT,
                FOREIGN KEY (meet_id) REFERENCES meetings(id)
            )
            """)
            # 读取现有字段，自动补全缺失检索字段
            cursor = conn.execute("PRAGMA table_info(meetings);")
            columns = [row[1] for row in cursor.fetchall()]
            add_fields = [
                ("meeting_type", "TEXT"),
                ("todo_person", "TEXT"),
                ("keyword_tags", "TEXT"),
                ("is_archive", "INTEGER DEFAULT 0")
            ]
            for col_name, col_type in add_fields:
                if col_name not in columns:
                    conn.execute(f"ALTER TABLE meetings ADD COLUMN {col_name} {col_type};")

            # 创建索引，加速检索
            # 会议检索索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meet_title ON meetings(title);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meet_type ON meetings(meeting_type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meet_person ON meetings(todo_person);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meet_tags ON meetings(keyword_tags);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meet_time ON meetings(created_at);")
            # 任务筛选索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_meet ON todo_task(meet_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_owner ON todo_task(owner);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_deadline ON todo_task(deadline);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON todo_task(status);")
        logger.info("数据库初始化完成：会议多维检索表 + 标准化待办任务表")
    except Exception as e:
        logger.critical(f"数据库初始化失败: {str(e)}")
        raise

def _list_backups() -> list:
    """按修改时间升序列出所有备份文件"""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("meetings_*.db"), key=lambda p: p.stat().st_mtime)


def _prune_backups():
    """只保留最近 DB_BACKUP_KEEP 份备份，删除更旧的，避免 backups 目录无限膨胀"""
    backups = _list_backups()
    keep = max(1, config.DB_BACKUP_KEEP)
    for old in backups[:-keep]:
        try:
            os.remove(old)
            logger.info(f"清理过期数据库备份：{old.name}")
        except Exception as e:
            logger.warning(f"清理备份失败 {old}: {str(e)}")


def backup_db(force: bool = False):
    """
    自动备份数据库（低频、限量）：
    - 距上次备份不足 DB_BACKUP_MIN_INTERVAL_MIN 分钟则跳过；
    - 备份后仅保留最近 DB_BACKUP_KEEP 份。
    """
    if not os.path.exists(DB_PATH):
        return
    if not force:
        existing = _list_backups()
        if existing:
            newest_age_min = (
                datetime.now() - datetime.fromtimestamp(existing[-1].stat().st_mtime)
            ).total_seconds() / 60
            if newest_age_min < config.DB_BACKUP_MIN_INTERVAL_MIN:
                logger.info(
                    f"距上次备份仅 {newest_age_min:.0f} 分钟（阈值 "
                    f"{config.DB_BACKUP_MIN_INTERVAL_MIN} 分钟），跳过本次备份"
                )
                return
    time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_file = BACKUP_DIR / f"meetings_{time_str}.db"
    try:
        shutil.copy2(DB_PATH, bak_file)
        logger.info(f"数据库已备份：{bak_file}")
        _prune_backups()
    except Exception as e:
        logger.error(f"数据库备份失败: {str(e)}")

# ===================== 会议主表操作（改造后） =====================
def save_meeting(title, meeting_type, audio_path, transcript, summary, todos, todo_person="", keyword_tags="") -> int:
    """保存会议，返回会议自增ID（用于绑定任务）"""
    backup_db()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO meetings
                (title,meeting_type,audio_path,transcript,summary,todos,todo_person,keyword_tags,is_archive)
                VALUES(?,?,?,?,?,?,?,?,0)""",
                (title, meeting_type, audio_path, transcript, summary, todos, todo_person, keyword_tags)
            )
            meet_id = cur.lastrowid
        logger.info(f"新增会议记录：{title}，会议ID={meet_id}")
        return meet_id
    except Exception as e:
        logger.error(f"保存会议失败 {title}: {str(e)}")
        raise

def get_meeting_by_id(m_id: int) -> dict | None:
    """根据ID查询完整会议信息"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM meetings WHERE id = ?", (m_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"查询会议id={m_id}失败: {str(e)}")
        return None

def update_meeting(m_id: int, title=None, meeting_type=None, transcript=None, summary=None, todos=None, todo_person=None, keyword_tags=None, is_archive=None):
    backup_db()
    update_fields = []
    params = []
    if title is not None:
        update_fields.append("title = ?")
        params.append(title)
    if meeting_type is not None:
        update_fields.append("meeting_type = ?")
        params.append(meeting_type)
    if transcript is not None:
        update_fields.append("transcript = ?")
        params.append(transcript)
    if summary is not None:
        update_fields.append("summary = ?")
        params.append(summary)
    if todos is not None:
        update_fields.append("todos = ?")
        params.append(todos)
    if todo_person is not None:
        update_fields.append("todo_person = ?")
        params.append(todo_person)
    if keyword_tags is not None:
        update_fields.append("keyword_tags = ?")
        params.append(keyword_tags)
    if is_archive is not None:
        update_fields.append("is_archive = ?")
        params.append(is_archive)
    if not update_fields:
        logger.warning("无任何更新字段，跳过操作")
        return
    params.append(m_id)
    sql = f"UPDATE meetings SET {','.join(update_fields)} WHERE id = ?"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(sql, params)
        logger.info(f"更新会议 id={m_id}")
    except Exception as e:
        logger.error(f"更新会议id={m_id}失败: {str(e)}")
        raise

def delete_meeting(m_id: int):
    backup_db()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # 级联删除关联任务
            conn.execute("DELETE FROM todo_task WHERE meet_id = ?", (m_id,))
            conn.execute("DELETE FROM meetings WHERE id = ?", (m_id,))
        logger.info(f"删除会议 id={m_id}，关联任务已清空")
    except Exception as e:
        logger.error(f"删除会议id={m_id}失败: {str(e)}")
        raise

def batch_delete_meeting(id_list: list[int]):
    if not id_list:
        return
    backup_db()
    placeholders = ",".join(["?"] * len(id_list))
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(f"DELETE FROM todo_task WHERE meet_id IN ({placeholders})", id_list)
            conn.execute(f"DELETE FROM meetings WHERE id IN ({placeholders})", id_list)
        logger.info(f"批量删除会议 {id_list} 及对应任务")
    except Exception as e:
        logger.error(f"批量删除失败 {id_list}: {str(e)}")
        raise

# ===================== 多维智能检索：会议分页查询 =====================
def list_meetings(
    page=1,
    page_size=15,
    keyword="",
    meeting_type="",
    person="",
    start_date="",
    end_date="",
    show_archive=None
):
    offset = (page - 1) * page_size
    sql_where = []
    params = []
    # 全局关键词：标题/全文/摘要/关键词标签
    if keyword.strip():
        sql_where.append("(title LIKE ? OR transcript LIKE ? OR summary LIKE ? OR keyword_tags LIKE ?)")
        val = f"%{keyword}%"
        params.extend([val, val, val, val])
    # 会议类型筛选
    if meeting_type.strip():
        sql_where.append("meeting_type LIKE ?")
        params.append(f"%{meeting_type}%")
    # 责任人筛选
    if person.strip():
        sql_where.append("todo_person LIKE ?")
        params.append(f"%{person}%")
    # 日期区间
    if start_date.strip():
        sql_where.append("created_at >= ?")
        params.append(f"{start_date} 00:00:00")
    if end_date.strip():
        sql_where.append("created_at <= ?")
        params.append(f"{end_date} 23:59:59")
    # 归档状态
    if show_archive is not None:
        sql_where.append("is_archive = ?")
        params.append(show_archive)

    where_sql = " AND ".join(sql_where) if sql_where else "1=1"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            count_sql = f"SELECT COUNT(*) total FROM meetings WHERE {where_sql}"
            total = conn.execute(count_sql, params).fetchone()[0]
            data_sql = f"""
                SELECT id,title,meeting_type,audio_path,created_at,is_archive,todo_person,keyword_tags
                FROM meetings
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
            """
            params.extend([page_size, offset])
            rows = conn.execute(data_sql, params).fetchall()
            data = [dict(r) for r in rows]
        return data, total
    except Exception as e:
        logger.error(f"多维分页查询失败: {str(e)}")
        return [], 0

# ===================== 标准化待办任务 CRUD（跟踪核心） =====================
def batch_insert_tasks(meet_id: int, task_list: list[dict]):
    """AI提取任务后批量写入独立任务表"""
    if not task_list:
        return
    backup_db()
    insert_sql = """
    INSERT INTO todo_task (meet_id,task_content,owner,deadline,priority)
    VALUES (?,?,?,?,?)
    """
    params = []
    for task in task_list:
        params.append((
            meet_id,
            task.get("task_content",""),
            task.get("owner","未知"),
            task.get("deadline","无"),
            task.get("priority","中")
        ))
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany(insert_sql, params)
        logger.info(f"会议{meet_id}批量插入{len(task_list)}条标准化待办任务")
    except Exception as e:
        logger.error(f"批量写入任务失败：{str(e)}")
        raise

def update_task_status(task_id:int, status:str, finish_at:str=None):
    """更新任务状态：待处理/进行中/已完成/已延期（任务跟踪核心）"""
    backup_db()
    sql = "UPDATE todo_task SET status=?, finish_at=? WHERE task_id=?"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(sql, (status, finish_at, task_id))
        logger.info(f"更新任务{task_id}状态为：{status}")
    except Exception as e:
        logger.error(f"任务状态更新失败：{str(e)}")
        raise

def list_tasks(page=1,page_size=15,owner="",status="",priority="",start_dead="",end_dead=""):
    """多维筛选任务：负责人/状态/优先级/截止日期"""
    offset = (page-1)*page_size
    where = []
    params = []
    if owner.strip():
        where.append("owner LIKE ?")
        params.append(f"%{owner}%")
    if status.strip():
        where.append("status = ?")
        params.append(status)
    if priority.strip():
        where.append("priority = ?")
        params.append(priority)
    if start_dead.strip():
        where.append("deadline >= ?")
        params.append(start_dead)
    if end_dead.strip():
        where.append("deadline <= ?")
        params.append(end_dead)
    where_sql = " AND ".join(where) if where else "1=1"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            count_sql = f"SELECT COUNT(*) FROM todo_task WHERE {where_sql}"
            total = conn.execute(count_sql, params).fetchone()[0]
            data_sql = f"""
            SELECT t.*,m.title meet_title
            FROM todo_task t
            LEFT JOIN meetings m ON t.meet_id = m.id
            WHERE {where_sql}
            ORDER BY deadline ASC, priority DESC
            LIMIT ? OFFSET ?
            """
            params.extend([page_size, offset])
            rows = conn.execute(data_sql, params).fetchall()
            data = [dict(i) for i in rows]
        return data, total
    except Exception as e:
        logger.error(f"任务查询失败：{str(e)}")
        return [],0
    
def delete_task(task_id: int):
    """删除单条待办任务"""
    backup_db()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM todo_task WHERE task_id = ?", (task_id,))
        logger.info(f"删除任务 task_id={task_id}")
    except Exception as e:
        logger.error(f"删除任务失败: {str(e)}")
        raise