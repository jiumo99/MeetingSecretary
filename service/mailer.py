import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import config
from utils.logger import get_logger, mask_secret

logger = get_logger("mailer")

# 统一读取配置
MAIL_SENDER = config.MY_EMAIL
MAIL_PWD = config.MY_EMAIL_PASS
SMTP_SERVER = config.SMTP_SERVER
SMTP_PORT = config.SMTP_PORT

# 邮箱正则校验
EMAIL_REG = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

def send_todo_email(to_addr: str, meeting_title: str, todo_text: str):
    # 前置校验邮箱格式
    if not EMAIL_REG.match(to_addr):
        logger.warning(f"邮箱格式非法：{to_addr}")
        raise ValueError(f"邮箱地址 {to_addr} 格式不正确")

    logger.info(f"准备发送邮件，收件人：{mask_secret(to_addr)}，会议标题：{meeting_title}")
    if not MAIL_SENDER or not MAIL_PWD:
        logger.error("邮箱配置缺失，无法发送邮件")
        raise RuntimeError("系统邮箱未配置完整，请检查.env邮件参数")

    # 构造邮件
    msg = MIMEMultipart("alternative")
    msg["From"] = MAIL_SENDER
    msg["To"] = to_addr
    msg["Subject"] = f"【会议待办】{meeting_title}"

    # 提前处理换行，避免f-string内出现\
    todo_html = todo_text.replace("\n", "<br>")
    html_content = f"""
    <div style="font-family:Microsoft YaHei;">
        <h2>会议待办任务通知</h2>
        <p>会议名称：{meeting_title}</p>
        <hr/>
        <h3>待办清单</h3>
        <p style="line-height:1.8;">{todo_html}</p>
    </div>
    """
    text_content = f"会议：{meeting_title}\n待办任务：\n{todo_text}"
    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        # 连接SMTP发送
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(MAIL_SENDER, MAIL_PWD)
        server.send_message(msg)
        server.quit()
        logger.info(f"邮件发送成功，收件人：{mask_secret(to_addr)}")
    except Exception as e:
        logger.error(f"邮件发送失败 {to_addr}: {str(e)}", exc_info=True)
        raise RuntimeError(f"邮件发送失败：{str(e)}")