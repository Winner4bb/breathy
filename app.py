from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)
import requests
import urllib.parse
import os

# ---------- CONFIG ----------
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
AQICN_API = os.getenv("AQICN_API")

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    raise ValueError("กรุณาตั้งค่า CHANNEL_ACCESS_TOKEN และ CHANNEL_SECRET ใน Config Vars ของ Heroku")

app = Flask(__name__)
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ---------- CONSTANTS ----------
SYMPTOM_OPTIONS = ["ไอ", "จาม", "หายใจมีเสียงวี้ด", "แน่นหน้าอก", "เหนื่อยง่าย"]
CITY_OPTIONS = ["กรุงเทพ", "เชียงใหม่", "ภูเก็ต", "ขอนแก่น"]
# แผนที่ชื่อเมือง → ชื่อที่ AQICN เข้าใจ
CITY_API_NAME = {
    "กรุงเทพ": "Bangkok",
    "เชียงใหม่": "Chiang Mai",
    "ภูเก็ต": "Phuket",
    "ขอนแก่น": "Khon Kaen",
}

# โครงสร้าง session: user_id -> {step, age, smoker, family, symptoms:[]}
user_data = {}

# ---------- HELPERS ----------
def qr_smoker():
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="สูบบุหรี่", text="smoker:y")),
        QuickReplyButton(action=MessageAction(label="ไม่สูบบุหรี่", text="smoker:n")),
        QuickReplyButton(action=MessageAction(label="ยกเลิก", text="ยกเลิก")),
    ])

def qr_family():
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="มีประวัติหอบหืด", text="family:y")),
        QuickReplyButton(action=MessageAction(label="ไม่มีประวัติ", text="family:n")),
        QuickReplyButton(action=MessageAction(label="ยกเลิก", text="ยกเลิก")),
    ])

def qr_symptoms():
    items = [
        QuickReplyButton(action=MessageAction(label=label, text=f"อาการ:{label}"))
        for label in SYMPTOM_OPTIONS
    ]
    # ปุ่มจบการเลือกอาการ
    items.append(QuickReplyButton(action=MessageAction(label="เลือกเสร็จแล้ว", text="symptoms:done")))
    items.append(QuickReplyButton(action=MessageAction(label="ยกเลิก", text="ยกเลิก")))
    return QuickReply(items=items)

def qr_city():
    items = [
        QuickReplyButton(action=MessageAction(label=label, text=f"เมือง:{label}"))
        for label in CITY_OPTIONS
    ]
    items.append(QuickReplyButton(action=MessageAction(label="ยกเลิก", text="ยกเลิก")))
    return QuickReply(items=items)

def reset_session(user_id):
    user_data.pop(user_id, None)

def ensure_session(user_id):
    if user_id not in user_data:
        user_data[user_id] = {
            "step": None, "age": None, "smoker": None,
            "family": None, "symptoms": []
        }

def get_aqi(city_label):
    """ดึงค่า AQI ตามชื่อเมืองที่เลือก"""
    api_city = CITY_API_NAME.get(city_label, city_label)
    try:
        url = f"https://api.waqi.info/feed/{urllib.parse.quote(api_city)}/?token={AQICN_API}"
        r = requests.get(url, timeout=5).json()
        if r.get("status") == "ok":
            return r["data"].get("aqi")
    except Exception as e:
        print(f"[AQI ERROR] {e}")
    return None

def assess_risk(age, smoker, family_history, symptoms, aqi):
    score = 0
    if age < 12 or age > 60:
        score += 1
    if smoker:
        score += 2
    if family_history:
        score += 2
    score += len(symptoms)
    if aqi is not None and aqi > 100:
        score += 2

    if score <= 2:
        return "ต่ำ", "เดินทางได้ตามปกติ ดูแลสุขภาพทั่วไป"
    elif score <= 5:
        return "ปานกลาง", "ระวัง พกยา inhaler, ใส่หน้ากาก, หลีกเลี่ยงฝุ่น/ควัน"
    else:
        return "สูง", "ไม่ควรเดินทาง ควรปรึกษาแพทย์ก่อน"

# ---------- ROUTES ----------
@app.route("/", methods=["GET"])
def home():
    return "✅ LINE Bot is running."

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ---------- HANDLER ----------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text_raw = event.message.text.strip()
    text = text_raw.lower()
    user_id = event.source.user_id

    # คำสั่งกลาง: ยกเลิก / เริ่มใหม่
    if text in ["ยกเลิก", "cancel", "stop"]:
        reset_session(user_id)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="ยกเลิกกระบวนการแล้วครับ ✅\nพิมพ์ \"ประเมิน\" เพื่อเริ่มใหม่")
        )
        return

    # เริ่มกระบวนการ
    if text in ["ประเมิน", "เริ่ม", "start"]:
        user_data[user_id] = {
            "step": "ask_age", "age": None, "smoker": None,
            "family": None, "symptoms": []
        }
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="กรุณาใส่อายุของคุณ (ตัวเลข 1–120):")
        )
        return

    # ถ้าไม่มี session ให้ชวนเริ่ม
    if user_id not in user_data or not user_data[user_id].get("step"):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="พิมพ์ \"ประเมิน\" เพื่อเริ่มประเมินอาการนะครับ")
        )
        return

    # อ่านสถานะปัจจุบัน
    state = user_data[user_id]["step"]

    # -------- STEP: อายุ --------
    if state == "ask_age":
        # รับเฉพาะตัวเลขในช่วงเหมาะสม
        if text.isdigit():
            age = int(text)
            if 1 <= age <= 120:
                user_data[user_id]["age"] = age
                user_data[user_id]["step"] = "ask_smoker"
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="คุณสูบบุหรี่หรือไม่?", quick_reply=qr_smoker())
                )
                return
        # ไม่ถูกต้อง -> ไม่ขยับสถานะ
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ กรุณาใส่อายุเป็นตัวเลข 1–120 เท่านั้น")
        )
        return

    # -------- STEP: สูบบุหรี่ --------
    if state == "ask_smoker":
        if text.startswith("smoker:"):
            val = text.split(":", 1)[1]
            if val in ["y", "n"]:
                user_data[user_id]["smoker"] = (val == "y")
                user_data[user_id]["step"] = "ask_family"
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="มีประวัติหอบหืดในครอบครัวหรือไม่?", quick_reply=qr_family())
                )
                return
        # ไม่ใช่คำตอบที่กำหนด
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ กรุณาเลือกด้วยปุ่มด้านล่าง", quick_reply=qr_smoker())
        )
        return

    # -------- STEP: ประวัติครอบครัว --------
    if state == "ask_family":
        if text.startswith("family:"):
            val = text.split(":", 1)[1]
            if val in ["y", "n"]:
                user_data[user_id]["family"] = (val == "y")
                user_data[user_id]["step"] = "ask_symptoms"
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="เลือกอาการของคุณ (กดได้หลายครั้ง) แล้วกด \"เลือกเสร็จแล้ว\"",
                        quick_reply=qr_symptoms()
                    )
                )
                return
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ กรุณาเลือกด้วยปุ่มด้านล่าง", quick_reply=qr_family())
        )
        return

    # -------- STEP: เลือกอาการ (หลายครั้ง) --------
    if state == "ask_symptoms":
        # เพิ่มอาการถ้าอยู่ในลิสต์
        if text.startswith("อาการ:"):
            symp = text_raw.replace("อาการ:", "", 1).strip()
            if symp in SYMPTOM_OPTIONS:
                # กันซ้ำ
                if symp not in user_data[user_id]["symptoms"]:
                    user_data[user_id]["symptoms"].append(symp)
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text=f"บันทึกอาการ: {symp}\nเลือกเพิ่มหรือกด \"เลือกเสร็จแล้ว\"",
                        quick_reply=qr_symptoms()
                    )
                )
                return
            else:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="⚠️ อาการนี้ไม่มีในตัวเลือก กรุณาเลือกจากปุ่มด้านล่าง",
                        quick_reply=qr_symptoms()
                    )
                )
                return

        # จบการเลือกอาการ
        if text in ["symptoms:done", "เลือกเสร็จแล้ว"]:
            if not user_data[user_id]["symptoms"]:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="⚠️ กรุณาเลือกอย่างน้อย 1 อาการก่อนกด \"เลือกเสร็จแล้ว\"",
                        quick_reply=qr_symptoms()
                    )
                )
                return
            user_data[user_id]["step"] = "ask_city"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="เลือกเมืองที่จะไป:", quick_reply=qr_city())
            )
            return

        # อื่น ๆ ที่ไม่ใช่ตัวเลือก
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ กรุณาเลือกอาการจากปุ่ม หรือกด \"เลือกเสร็จแล้ว\"", quick_reply=qr_symptoms())
        )
        return

    # -------- STEP: เลือกเมือง --------
    if state == "ask_city":
        if text.startswith("เมือง:"):
            city_label = text_raw.replace("เมือง:", "", 1).strip()
            if city_label in CITY_OPTIONS:
                data = user_data[user_id]
                aqi = get_aqi(city_label)
                level, advice = assess_risk(
                    data["age"], data["smoker"], data["family"], data["symptoms"], aqi
                )
                reply = f"""📌 แบบประเมินความเสี่ยงโรคหอบหืด
อายุ: {data['age']}, สูบบุหรี่: {data['smoker']}, ครอบครัว: {data['family']}
อาการ: {', '.join(data['symptoms'])}

🌫 AQI ({city_label}): {aqi if aqi is not None else 'ไม่สามารถดึงค่าได้'}

⚠️ ระดับความเสี่ยง: {level}
💡 คำแนะนำ: {advice}"""
                reset_session(user_id)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                return
            else:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="⚠️ เมืองนี้ไม่มีในตัวเลือก กรุณาเลือกจากปุ่มด้านล่าง", quick_reply=qr_city())
                )
                return

        # อื่น ๆ ที่ไม่ใช่ตัวเลือก
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ กรุณาเลือกเมืองจากปุ่มด้านล่าง", quick_reply=qr_city())
        )
        return

    # กันตกหล่น
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="พิมพ์ \"ประเมิน\" เพื่อเริ่มประเมินอาการครับ")
    )

# ---------- RUN ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
